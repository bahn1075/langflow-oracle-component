from __future__ import annotations

import json
import queue
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from lfx.base.data import BaseFileComponent
from lfx.base.data.docling_utils import _serialize_pydantic_model, docling_worker
from lfx.inputs import BoolInput, DropdownInput, HandleInput, IntInput, StrInput
from lfx.schema import Data


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


def _safe_json_loads(raw: Any) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _is_rollout_entry(entry: Any) -> bool:
    return isinstance(entry, dict) and "type" in entry and "payload" in entry


def _load_rollout_entries(source_path: Path) -> list[dict[str, Any]] | None:
    suffix = source_path.suffix.lower()
    raw = source_path.read_text(encoding="utf-8")

    if suffix == ".jsonl":
        entries = [json.loads(line) for line in raw.splitlines() if line.strip()]
        return entries if entries and all(_is_rollout_entry(entry) for entry in entries) else None

    if suffix != ".json":
        return None

    parsed = json.loads(raw)
    if isinstance(parsed, list) and parsed and all(_is_rollout_entry(entry) for entry in parsed):
        return parsed
    if isinstance(parsed, dict) and isinstance(parsed.get("events"), list):
        events = parsed["events"]
        return events if events and all(_is_rollout_entry(entry) for entry in events) else None

    return None


def _format_argument_summary(tool_name: str, arguments: Any) -> str:
    if isinstance(arguments, dict):
        if tool_name == "exec_command" and arguments.get("cmd"):
            return str(arguments["cmd"]).strip()
        if tool_name == "parallel" and isinstance(arguments.get("tool_uses"), list):
            return f"{len(arguments['tool_uses'])} parallel tool calls"
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

    return _clean_tool_output("\n".join(parts))


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
                block = {
                    "kind": "tool",
                    "tool_name": payload.get("name", "tool"),
                    "call_id": call_id,
                    "arguments": _safe_json_loads(payload.get("arguments")),
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

                tool_block["aggregated_output"] = payload.get("aggregated_output", "")
                tool_block["formatted_output"] = payload.get("formatted_output", "")
                tool_block["stdout"] = payload.get("stdout", "")
                tool_block["stderr"] = payload.get("stderr", "")
                tool_block["exit_code"] = payload.get("exit_code")
                continue

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
        summary = _format_argument_summary(tool_name, block.get("arguments"))
        exit_code = block.get("exit_code")

        if tool_render_mode == "Hide":
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
    if isinstance(environment_context, dict):
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

        lines.extend([f"### {index}. Tool `{block['tool_name']}`", "", f"- Summary: {block['summary']}"])
        exit_code = block.get("exit_code")
        if exit_code not in (None, 0):
            lines.append(f"- Exit code: `{exit_code}`")
        if block.get("output"):
            lines.extend(["", "```text", block["output"], "```"])
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
) -> str:
    resolved_path = Path(source_path).expanduser().resolve()
    entries = _load_rollout_entries(resolved_path)
    if entries is None:
        msg = f"File is not a supported Codex rollout JSON/JSONL: {resolved_path}"
        raise ValueError(msg)

    blocks, metadata = _extract_blocks(
        entries,
        include_commentary=include_commentary,
        include_developer_messages=include_developer_messages,
        tool_render_mode=tool_render_mode,
        max_tool_output_chars=max_tool_output_chars,
        strip_environment_context=strip_environment_context,
    )

    if not include_session_metadata:
        metadata = {}

    metadata["source_file"] = str(resolved_path)
    return _render_markdown(blocks, metadata, resolved_path)


class CodexRolloutDoclingInlineComponent(BaseFileComponent):
    display_name = "Docling Rollout"
    description = (
        "Uses Docling to process input documents locally and automatically converts Codex rollout JSON/JSONL "
        "files into markdown before creating DoclingDocument output."
    )
    documentation = "https://docling-project.github.io/docling/"
    trace_type = "tool"
    icon = "Docling"
    name = "CodexRolloutDoclingInline"

    VALID_EXTENSIONS = [
        "adoc",
        "asciidoc",
        "asc",
        "bmp",
        "csv",
        "dotx",
        "dotm",
        "docm",
        "docx",
        "htm",
        "html",
        "jpeg",
        "json",
        "jsonl",
        "md",
        "pdf",
        "png",
        "potx",
        "ppsx",
        "pptm",
        "potm",
        "ppsm",
        "pptx",
        "tiff",
        "txt",
        "xls",
        "xlsx",
        "xhtml",
        "xml",
        "webp",
    ]

    inputs = [
        *BaseFileComponent.get_base_inputs(),
        DropdownInput(
            name="pipeline",
            display_name="Pipeline",
            info="Docling pipeline to use",
            options=["standard", "vlm"],
            value="standard",
        ),
        DropdownInput(
            name="ocr_engine",
            display_name="OCR Engine",
            info="OCR engine to use. None will disable OCR.",
            options=["None", "easyocr", "tesserocr", "rapidocr", "ocrmac"],
            value="None",
        ),
        BoolInput(
            name="do_picture_classification",
            display_name="Picture classification",
            info="If enabled, the Docling pipeline will classify the picture type.",
            value=False,
        ),
        HandleInput(
            name="pic_desc_llm",
            display_name="Picture description LLM",
            info="If connected, the model to use for picture description.",
            input_types=["LanguageModel"],
            required=False,
        ),
        StrInput(
            name="pic_desc_prompt",
            display_name="Picture description prompt",
            value="Describe the image in three sentences. Be concise and accurate.",
            info="The user prompt to use when invoking the model.",
            advanced=True,
        ),
        BoolInput(
            name="include_session_metadata",
            display_name="Include Session Metadata",
            value=True,
            info="Include session, model, git, and environment metadata in generated markdown before Docling parsing.",
            advanced=True,
        ),
        BoolInput(
            name="include_commentary",
            display_name="Include Assistant Commentary",
            value=True,
            info="Keep assistant commentary messages when converting rollout files to markdown.",
            advanced=True,
        ),
        DropdownInput(
            name="tool_render_mode",
            display_name="Tool Mode",
            options=["Hide", "Summary", "Summary + Output"],
            value="Hide",
            real_time_refresh=True,
            info="Choose how much tool activity to include when rendering rollout markdown.",
            advanced=True,
        ),
        IntInput(
            name="max_tool_output_chars",
            display_name="Max Tool Output Characters",
            value=1200,
            info="Trim long tool outputs when Tool Mode is set to Summary + Output.",
            advanced=True,
        ),
        BoolInput(
            name="include_developer_messages",
            display_name="Include Developer Messages",
            value=False,
            info="Include developer/system prompt content in generated markdown.",
            advanced=True,
        ),
        BoolInput(
            name="strip_environment_context",
            display_name="Strip Environment Context From Transcript",
            value=True,
            info="Move the environment_context block into session metadata.",
            advanced=True,
        ),
    ]

    outputs = [
        *BaseFileComponent.get_base_outputs(),
    ]

    def update_build_config(self, build_config: dict[str, Any], field_value: Any, field_name: str | None = None) -> dict[str, Any]:
        if field_name == "tool_render_mode":
            build_config["max_tool_output_chars"]["show"] = field_value == "Summary + Output"
        return build_config

    def _wait_for_result_with_thread_monitoring(
        self,
        result_queue: queue.Queue,
        thread: threading.Thread,
        timeout: int = 300,
    ):
        start_time = time.time()

        while time.time() - start_time < timeout:
            if not thread.is_alive():
                try:
                    result = result_queue.get_nowait()
                except queue.Empty:
                    msg = "Worker thread crashed unexpectedly without producing result."
                    raise RuntimeError(msg) from None
                else:
                    self.log("Thread completed and result retrieved")
                    return result

            try:
                result = result_queue.get(timeout=1)
            except queue.Empty:
                continue
            else:
                self.log("Result received from worker thread")
                return result

        msg = f"Thread timed out after {timeout} seconds"
        raise TimeoutError(msg)

    def _stop_thread_gracefully(self, thread: threading.Thread, timeout: int = 10):
        if not thread.is_alive():
            return

        self.log("Waiting for thread to complete gracefully")
        thread.join(timeout=timeout)

        if thread.is_alive():
            self.log("Warning: Thread still alive after timeout")

    def _prepare_docling_inputs(
        self,
        file_list: list[BaseFileComponent.BaseFile],
    ) -> tuple[list[Path], dict[str, str], dict[str, str], list[Path]]:
        prepared_paths: list[Path] = []
        path_map: dict[str, str] = {}
        generated_markdowns: dict[str, str] = {}
        temp_paths: list[Path] = []

        for file in file_list:
            if not file.path:
                continue

            original_path = Path(file.path)
            ext = original_path.suffix.lower()
            prepared_path = original_path

            if ext in {".json", ".jsonl"}:
                rollout_entries = _load_rollout_entries(original_path)
                if rollout_entries is not None:
                    markdown = convert_codex_rollout_to_markdown(
                        original_path,
                        include_commentary=bool(self.include_commentary),
                        include_developer_messages=bool(self.include_developer_messages),
                        include_session_metadata=bool(self.include_session_metadata),
                        tool_render_mode=str(self.tool_render_mode),
                        max_tool_output_chars=int(self.max_tool_output_chars),
                        strip_environment_context=bool(self.strip_environment_context),
                    )

                    temp_file = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8")
                    try:
                        temp_file.write(markdown)
                        temp_file.flush()
                        prepared_path = Path(temp_file.name)
                    finally:
                        temp_file.close()

                    temp_paths.append(prepared_path)
                    path_map[str(prepared_path)] = str(original_path)
                    generated_markdowns[str(original_path)] = markdown
                    self.log(f"Converted rollout file to temporary markdown: {original_path}")
                elif ext == ".jsonl":
                    msg = f"JSONL file is not a supported Codex rollout session: {original_path}"
                    raise ValueError(msg)

            prepared_paths.append(prepared_path)

        return prepared_paths, path_map, generated_markdowns, temp_paths

    def process_files(self, file_list: list[BaseFileComponent.BaseFile]) -> list[BaseFileComponent.BaseFile]:
        try:
            from docling.document_converter import DocumentConverter  # noqa: F401
        except ImportError as e:
            msg = (
                "Docling is an optional dependency. Install with `uv pip install 'langflow[docling]'` or refer to the "
                "documentation on how to install optional dependencies."
            )
            raise ImportError(msg) from e

        if not file_list:
            self.log("No files to process.")
            return file_list

        file_paths, path_map, generated_markdowns, temp_paths = self._prepare_docling_inputs(file_list)
        if not file_paths:
            self.log("No valid file paths to process.")
            return file_list

        pic_desc_config: dict | None = None
        if self.pic_desc_llm is not None:
            pic_desc_config = _serialize_pydantic_model(self.pic_desc_llm)

        result_queue: queue.Queue = queue.Queue()
        thread = threading.Thread(
            target=docling_worker,
            kwargs={
                "file_paths": file_paths,
                "queue": result_queue,
                "pipeline": self.pipeline,
                "ocr_engine": self.ocr_engine,
                "do_picture_classification": self.do_picture_classification,
                "pic_desc_config": pic_desc_config,
                "pic_desc_prompt": self.pic_desc_prompt,
            },
            daemon=False,
        )

        result = None
        thread.start()

        try:
            result = self._wait_for_result_with_thread_monitoring(result_queue, thread, timeout=300)
        except KeyboardInterrupt:
            self.log("Docling thread cancelled by user")
            result = []
        except Exception as e:
            self.log(f"Error during processing: {e}")
            raise
        finally:
            self._stop_thread_gracefully(thread)
            for temp_path in temp_paths:
                try:
                    temp_path.unlink(missing_ok=True)
                except Exception:
                    self.log(f"Warning: Failed to remove temporary markdown file: {temp_path}")

        if isinstance(result, dict) and "error" in result:
            error_msg = result["error"]

            if result.get("error_type") == "dependency_error":
                dependency_name = result.get("dependency_name", "Unknown dependency")
                install_command = result.get("install_command", "Please check documentation")
                user_message = (
                    f"Missing OCR dependency: {dependency_name}. "
                    f"{install_command} "
                    f"Alternatively, you can set OCR Engine to 'None' to disable OCR processing."
                )
                raise ImportError(user_message)

            if error_msg.startswith("Docling is not installed"):
                raise ImportError(error_msg)

            if "Worker interrupted by SIGINT" in error_msg or "shutdown" in result:
                self.log("Docling process cancelled by user")
                result = []
            else:
                raise RuntimeError(error_msg)

        processed_data = []
        for row in result:
            if not row:
                processed_data.append(None)
                continue

            raw_file_path = str(row["file_path"])
            original_file_path = path_map.get(raw_file_path, raw_file_path)
            generated_markdown = generated_markdowns.get(original_file_path)

            payload = {
                "doc": row["document"],
                "file_path": original_file_path,
            }
            if generated_markdown:
                payload["converted_markdown"] = generated_markdown

            processed_data.append(
                Data(
                    text=generated_markdown,
                    data=payload,
                )
            )

        return self.rollup_data(file_list, processed_data)
