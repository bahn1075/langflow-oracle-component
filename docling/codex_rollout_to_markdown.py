from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from lfx.custom import Component
from lfx.io import BoolInput, DropdownInput, FileInput, IntInput, Output, StrInput
from lfx.schema.data import Data
from lfx.schema.message import Message


NOISE_LINE_PREFIXES = (
    "Chunk ID:",
    "Wall time:",
    "Original token count:",
    "Process exited with code",
    "Process running with session ID",
    "Total output lines:",
)

EVENTS_WITHOUT_PAYLOAD = {"reasoning", "token_count", "task_started", "task_complete"}

ENVIRONMENT_TAGS = ("cwd", "shell", "current_date", "timezone")


def _clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    clipped = text[: max_chars - 1].rstrip()
    return f"{clipped}\n... (truncated)"


def _extract_text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return _clean_text(content)
    if not isinstance(content, list):
        return ""

    chunks: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            chunks.append(text)

    return _clean_text("\n".join(chunks))


def _parse_environment_context(text: str) -> dict[str, str]:
    if "<environment_context>" not in text:
        return {}

    parsed: dict[str, str] = {}
    for tag in ENVIRONMENT_TAGS:
        match = re.search(rf"<{tag}>\s*(.*?)\s*</{tag}>", text, re.DOTALL)
        if match:
            parsed[tag] = match.group(1).strip()
    return parsed


def _strip_environment_context(text: str) -> str:
    stripped = re.sub(r"<environment_context>.*?</environment_context>", "", text, flags=re.DOTALL)
    return _clean_text(stripped)


def _load_rollout_entries(source_path: Path) -> list[dict[str, Any]]:
    raw = source_path.read_text(encoding="utf-8")
    suffix = source_path.suffix.lower()

    if suffix == ".jsonl":
        return [json.loads(line) for line in raw.splitlines() if line.strip()]

    parsed = json.loads(raw)
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict) and isinstance(parsed.get("events"), list):
        return parsed["events"]

    msg = "Expected a JSON array or a JSON object with an 'events' list."
    raise ValueError(msg)


def _safe_json_loads(raw: Any) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _format_argument_summary(tool_name: str, arguments: Any) -> str:
    if isinstance(arguments, dict):
        if tool_name == "exec_command" and arguments.get("cmd"):
            return str(arguments["cmd"]).strip()
        if tool_name == "parallel" and isinstance(arguments.get("tool_uses"), list):
            return f"{len(arguments['tool_uses'])} parallel tool calls"
        if tool_name in {"search_query", "image_query"}:
            queries = arguments.get(tool_name, [])
            if isinstance(queries, list) and queries:
                first_query = queries[0]
                if isinstance(first_query, dict) and first_query.get("q"):
                    return str(first_query["q"]).strip()
        if arguments.get("query"):
            return str(arguments["query"]).strip()
        if arguments.get("q"):
            return str(arguments["q"]).strip()
        return _truncate(json.dumps(arguments, ensure_ascii=False, indent=2), 300)
    if isinstance(arguments, str):
        return _truncate(arguments.strip(), 300)
    return str(arguments)


def _clean_tool_output(output: str) -> str:
    lines = output.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cleaned: list[str] = []

    for line in lines:
        stripped = line.rstrip()
        if stripped == "Output:":
            continue
        if any(stripped.startswith(prefix) for prefix in NOISE_LINE_PREFIXES):
            continue
        cleaned.append(line)

    return _clean_text("\n".join(cleaned))


def _best_exec_output(tool_block: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("aggregated_output", "formatted_output", "stdout", "stderr", "raw_output"):
        value = tool_block.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value)

    if not parts:
        return ""

    merged = "\n".join(parts)
    return _clean_tool_output(merged)


def _append_unique_block(blocks: list[dict[str, Any]], block: dict[str, Any]) -> None:
    if blocks:
        previous = blocks[-1]
        if (
            previous.get("kind") == block.get("kind")
            and previous.get("role") == block.get("role")
            and previous.get("phase") == block.get("phase")
            and previous.get("text") == block.get("text")
        ):
            return
    blocks.append(block)


def _extract_metadata(entries: list[dict[str, Any]]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}

    for entry in entries:
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            continue

        if entry.get("type") == "session_meta":
            metadata["session_id"] = payload.get("id")
            metadata["started_at"] = payload.get("timestamp")
            metadata["cwd"] = payload.get("cwd")
            metadata["originator"] = payload.get("originator")
            metadata["cli_version"] = payload.get("cli_version")
            metadata["source"] = payload.get("source")
            metadata["model_provider"] = payload.get("model_provider")
            git_payload = payload.get("git") or {}
            if isinstance(git_payload, dict):
                metadata["git_branch"] = git_payload.get("branch")
                metadata["git_commit"] = git_payload.get("commit_hash")
                metadata["git_repository_url"] = git_payload.get("repository_url")

        if entry.get("type") == "turn_context":
            metadata["current_date"] = payload.get("current_date")
            metadata["timezone"] = payload.get("timezone")
            metadata["model"] = payload.get("model")
            metadata["personality"] = payload.get("personality")
            collaboration_mode = payload.get("collaboration_mode") or {}
            if isinstance(collaboration_mode, dict):
                metadata["collaboration_mode"] = collaboration_mode.get("mode")

    return {key: value for key, value in metadata.items() if value not in (None, "", {})}


def _extract_blocks(
    entries: list[dict[str, Any]],
    *,
    include_commentary: bool,
    include_developer_messages: bool,
    tool_render_mode: str,
    max_tool_output_chars: int,
    strip_environment_context: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    metadata = _extract_metadata(entries)
    tool_calls: dict[str, dict[str, Any]] = {}

    for entry in entries:
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            continue

        entry_type = entry.get("type")
        timestamp = entry.get("timestamp")

        if entry_type == "response_item":
            subtype = payload.get("type")

            if subtype == "message":
                role = payload.get("role", "assistant")
                phase = payload.get("phase")
                text = _extract_text_from_content(payload.get("content"))
                if not text:
                    continue

                environment_context = _parse_environment_context(text)
                if environment_context:
                    metadata.setdefault("environment_context", {}).update(environment_context)
                    if strip_environment_context:
                        text = _strip_environment_context(text)

                if not text:
                    continue
                if role == "developer" and not include_developer_messages:
                    continue
                if role == "assistant" and phase == "commentary" and not include_commentary:
                    continue

                _append_unique_block(
                    blocks,
                    {
                        "kind": "message",
                        "role": role,
                        "phase": phase,
                        "text": text,
                        "timestamp": timestamp,
                    },
                )
                continue

            if tool_render_mode != "Hide" and subtype == "function_call":
                call_id = payload.get("call_id")
                if not call_id:
                    continue
                arguments = _safe_json_loads(payload.get("arguments"))
                block = {
                    "kind": "tool",
                    "tool_name": payload.get("name", "tool"),
                    "call_id": call_id,
                    "arguments": arguments,
                    "timestamp": timestamp,
                    "raw_output": "",
                    "aggregated_output": "",
                    "formatted_output": "",
                    "stdout": "",
                    "stderr": "",
                    "exit_code": None,
                }
                blocks.append(block)
                tool_calls[call_id] = block
                continue

            if tool_render_mode != "Hide" and subtype == "function_call_output":
                tool_block = tool_calls.get(payload.get("call_id"))
                if tool_block is not None:
                    tool_block["raw_output"] = payload.get("output", "")
                continue

        if entry_type == "event_msg":
            subtype = payload.get("type")
            if subtype in EVENTS_WITHOUT_PAYLOAD:
                continue

            if subtype == "exec_command_end" and tool_render_mode != "Hide":
                call_id = payload.get("call_id")
                if not call_id:
                    continue
                tool_block = tool_calls.get(call_id)
                if tool_block is None:
                    tool_block = {
                        "kind": "tool",
                        "tool_name": "exec_command",
                        "call_id": call_id,
                        "arguments": {},
                        "timestamp": timestamp,
                        "raw_output": "",
                        "aggregated_output": "",
                        "formatted_output": "",
                        "stdout": "",
                        "stderr": "",
                        "exit_code": None,
                    }
                    blocks.append(tool_block)
                    tool_calls[call_id] = tool_block

                command = payload.get("command")
                if isinstance(command, list) and command:
                    tool_block["command"] = " ".join(str(part) for part in command)
                tool_block["aggregated_output"] = payload.get("aggregated_output", "")
                tool_block["formatted_output"] = payload.get("formatted_output", "")
                tool_block["stdout"] = payload.get("stdout", "")
                tool_block["stderr"] = payload.get("stderr", "")
                tool_block["exit_code"] = payload.get("exit_code")
                continue

            if subtype == "web_search_end" and tool_render_mode != "Hide":
                query = payload.get("query")
                if not query:
                    action = payload.get("action") or {}
                    if isinstance(action, dict):
                        query = action.get("query")
                if query:
                    blocks.append(
                        {
                            "kind": "tool",
                            "tool_name": "web_search",
                            "call_id": payload.get("call_id"),
                            "arguments": {"query": query},
                            "timestamp": timestamp,
                            "raw_output": "",
                            "aggregated_output": "",
                            "formatted_output": "",
                            "stdout": "",
                            "stderr": "",
                            "exit_code": 0,
                        }
                    )

    rendered_blocks: list[dict[str, Any]] = []
    tool_count = 0
    message_count = 0

    for block in blocks:
        if block.get("kind") == "message":
            message_count += 1
            rendered_blocks.append(block)
            continue

        tool_name = str(block.get("tool_name", "tool"))
        output = _best_exec_output(block)
        arguments = block.get("arguments")
        summary = _format_argument_summary(tool_name, arguments)
        exit_code = block.get("exit_code")

        if tool_render_mode == "Hide":
            continue

        if tool_name == "web_search":
            continue

        if not output and exit_code in (None, 0):
            continue

        if tool_render_mode == "Summary":
            output = ""
        else:
            output = _truncate(output, max_tool_output_chars)

        rendered_blocks.append(
            {
                "kind": "tool",
                "tool_name": tool_name,
                "summary": summary,
                "output": output,
                "exit_code": exit_code,
                "timestamp": block.get("timestamp"),
            }
        )
        tool_count += 1

    metadata["message_count"] = message_count
    metadata["tool_count"] = tool_count
    metadata["entry_count"] = len(rendered_blocks)
    return rendered_blocks, metadata


def _render_markdown(blocks: list[dict[str, Any]], metadata: dict[str, Any], source_path: Path) -> str:
    lines = ["# Codex Rollout Session", ""]

    session_lines: list[str] = []
    for label, key in (
        ("Source file", "source_file"),
        ("Session ID", "session_id"),
        ("Started at", "started_at"),
        ("Working directory", "cwd"),
        ("Current date", "current_date"),
        ("Timezone", "timezone"),
        ("Model", "model"),
        ("Model provider", "model_provider"),
        ("Source", "source"),
        ("Originator", "originator"),
        ("CLI version", "cli_version"),
        ("Personality", "personality"),
        ("Collaboration mode", "collaboration_mode"),
        ("Git branch", "git_branch"),
        ("Git commit", "git_commit"),
        ("Git repository", "git_repository_url"),
    ):
        value = metadata.get(key)
        if value:
            session_lines.append(f"- {label}: `{value}`")

    environment_context = metadata.get("environment_context")
    if isinstance(environment_context, dict) and environment_context:
        for tag in ENVIRONMENT_TAGS:
            value = environment_context.get(tag)
            if value:
                session_lines.append(f"- Environment {tag}: `{value}`")

    if session_lines:
        lines.extend(["## Session Metadata", "", *session_lines, ""])

    lines.extend(["## Transcript", ""])

    if not blocks:
        lines.append("No meaningful transcript content was extracted.")
        return "\n".join(lines).strip()

    for index, block in enumerate(blocks, start=1):
        if block["kind"] == "message":
            role = str(block.get("role", "message")).title()
            phase = block.get("phase")
            heading = f"### {index}. {role}"
            if phase:
                heading = f"{heading} ({phase})"
            lines.extend([heading, "", block["text"], ""])
            continue

        heading = f"### {index}. Tool `{block['tool_name']}`"
        lines.extend([heading, "", f"- Summary: {block['summary']}"])

        exit_code = block.get("exit_code")
        if exit_code not in (None, 0):
            lines.append(f"- Exit code: `{exit_code}`")

        output = block.get("output")
        if output:
            lines.extend(["", "```text", output, "```"])

        lines.append("")

    metadata["source_file"] = str(source_path)
    return "\n".join(lines).strip()


def convert_codex_rollout_to_markdown(
    source_path: str | Path,
    *,
    include_commentary: bool = True,
    include_developer_messages: bool = False,
    include_session_metadata: bool = True,
    tool_render_mode: str = "Hide",
    max_tool_output_chars: int = 1200,
    strip_environment_context: bool = True,
) -> dict[str, Any]:
    resolved_path = Path(source_path).expanduser().resolve()
    if not resolved_path.exists():
        msg = f"Rollout file not found: {resolved_path}"
        raise FileNotFoundError(msg)

    entries = _load_rollout_entries(resolved_path)
    blocks, metadata = _extract_blocks(
        entries,
        include_commentary=include_commentary,
        include_developer_messages=include_developer_messages,
        tool_render_mode=tool_render_mode,
        max_tool_output_chars=max_tool_output_chars,
        strip_environment_context=strip_environment_context,
    )

    if not include_session_metadata:
        metadata = {
            "message_count": metadata.get("message_count", 0),
            "tool_count": metadata.get("tool_count", 0),
            "entry_count": metadata.get("entry_count", 0),
        }

    metadata["source_file"] = str(resolved_path)
    markdown = _render_markdown(blocks, metadata, resolved_path)
    return {
        "source_path": str(resolved_path),
        "markdown": markdown,
        "blocks": blocks,
        "metadata": metadata,
    }


def write_markdown_output(
    markdown: str,
    source_path: str | Path,
    *,
    output_directory: str = "",
    output_filename: str = "",
) -> Path:
    source = Path(source_path).expanduser().resolve()
    target_dir = Path(output_directory).expanduser() if output_directory else source.parent
    target_dir.mkdir(parents=True, exist_ok=True)

    if output_filename:
        filename = output_filename.strip()
    else:
        filename = f"{source.stem}.md"

    if not filename.lower().endswith(".md"):
        filename = f"{filename}.md"

    target_path = target_dir / filename
    target_path.write_text(markdown, encoding="utf-8")
    return target_path


class CodexRolloutToMarkdownComponent(Component):
    display_name = "Codex Rollout to Markdown"
    description = (
        "Convert a Codex VS Code rollout JSONL or JSON file into a cleaner Markdown transcript "
        "that keeps user, assistant, and optional tool activity."
    )
    icon = "file-text"
    name = "CodexRolloutToMarkdown"
    documentation = "https://github.com/openai/codex"

    inputs = [
        StrInput(
            name="source_path",
            display_name="Source Path",
            info="Absolute path to a Codex rollout .jsonl or converted .json file.",
        ),
        FileInput(
            name="rollout_file",
            display_name="Rollout File",
            info="Optional uploaded rollout file. Used when Source Path is empty.",
            file_types=["jsonl", "json"],
            required=False,
        ),
        BoolInput(
            name="include_session_metadata",
            display_name="Include Session Metadata",
            value=True,
            info="Include session, model, git, and environment metadata at the top of the markdown.",
        ),
        BoolInput(
            name="include_commentary",
            display_name="Include Assistant Commentary",
            value=True,
            info="Keep assistant commentary messages in addition to final answers.",
        ),
        DropdownInput(
            name="tool_render_mode",
            display_name="Tool Mode",
            options=["Hide", "Summary", "Summary + Output"],
            value="Hide",
            real_time_refresh=True,
            info="Choose how much tool activity to include in the markdown output.",
        ),
        IntInput(
            name="max_tool_output_chars",
            display_name="Max Tool Output Characters",
            value=1200,
            advanced=True,
            show=False,
            info="Trim long tool outputs when Tool Mode is set to Summary + Output.",
        ),
        BoolInput(
            name="include_developer_messages",
            display_name="Include Developer Messages",
            value=False,
            advanced=True,
            info="Include developer/system prompt content. Usually too noisy for chunking.",
        ),
        BoolInput(
            name="strip_environment_context",
            display_name="Strip Environment Context From Transcript",
            value=True,
            advanced=True,
            info="Move the environment_context block into session metadata instead of leaving it in the transcript.",
        ),
        StrInput(
            name="output_directory",
            display_name="Output Directory",
            advanced=True,
            info="Directory where the markdown file will be written. Defaults to the source file directory.",
        ),
        StrInput(
            name="output_filename",
            display_name="Output Filename",
            advanced=True,
            info="Optional markdown filename. Defaults to the source filename with a .md extension.",
        ),
    ]

    outputs = [
        Output(display_name="Markdown", name="markdown", method="build_markdown"),
        Output(display_name="Result", name="data", method="build_data"),
    ]

    def update_build_config(self, build_config: dict[str, Any], field_value: Any, field_name: str | None = None) -> dict[str, Any]:
        if field_name == "tool_render_mode":
            build_config["max_tool_output_chars"]["show"] = field_value == "Summary + Output"
        return build_config

    def _resolve_source_path(self) -> Path:
        if getattr(self, "source_path", ""):
            return Path(self.source_path).expanduser().resolve()

        uploaded = getattr(self, "rollout_file", None)
        if isinstance(uploaded, list):
            uploaded = next((item for item in uploaded if item), None)

        if uploaded:
            return Path(str(uploaded)).expanduser().resolve()

        msg = "Provide either Source Path or Rollout File."
        raise ValueError(msg)

    def _convert(self) -> dict[str, Any]:
        source_path = self._resolve_source_path()
        result = convert_codex_rollout_to_markdown(
            source_path,
            include_commentary=bool(self.include_commentary),
            include_developer_messages=bool(self.include_developer_messages),
            include_session_metadata=bool(self.include_session_metadata),
            tool_render_mode=str(self.tool_render_mode),
            max_tool_output_chars=int(self.max_tool_output_chars),
            strip_environment_context=bool(self.strip_environment_context),
        )
        output_path = write_markdown_output(
            result["markdown"],
            source_path,
            output_directory=str(getattr(self, "output_directory", "") or ""),
            output_filename=str(getattr(self, "output_filename", "") or ""),
        )
        result["output_path"] = str(output_path)
        self.status = f"Wrote markdown to {output_path}"
        return result

    def build_markdown(self) -> Message:
        result = self._convert()
        return Message(text=result["markdown"])

    def build_data(self) -> Data:
        result = self._convert()
        metadata = dict(result["metadata"])
        metadata["output_path"] = result["output_path"]
        return Data(text=result["markdown"], data=metadata)
