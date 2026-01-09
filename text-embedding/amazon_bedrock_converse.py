import os

from lfx.base.models.model import LCModelComponent
from lfx.field_typing import LanguageModel
from lfx.inputs.inputs import BoolInput, FloatInput, IntInput, MessageTextInput, SecretStrInput
from lfx.io import DictInput, DropdownInput


class AmazonBedrockConverseComponent(LCModelComponent):
    """Amazon Bedrock Converse API with secure credential handling."""

    display_name: str = "Amazon Bedrock Converse (Secure)"
    description: str = "Generate text using Amazon Bedrock LLMs with secure credential management and Converse API."
    icon = "Amazon"
    name = "AmazonBedrockConverseSecure"
    beta = True

    inputs = [
        *LCModelComponent.get_base_inputs(),
        DropdownInput(
            name="model_id",
            display_name="Model ID",
            options=[
                "anthropic.claude-3-5-sonnet-20241022-v2:0",
                "anthropic.claude-3-5-haiku-20241022-v1:0",
                "anthropic.claude-3-opus-20240229-v1:0",
                "anthropic.claude-3-sonnet-20240229-v1:0",
                "anthropic.claude-3-haiku-20240307-v1:0",
                "meta.llama3-1-405b-instruct-v1:0",
                "meta.llama3-1-70b-instruct-v1:0",
                "meta.llama3-1-8b-instruct-v1:0",
                "mistral.mistral-large-2407-v1:0",
                "mistral.mistral-small-2402-v1:0",
            ],
            value="anthropic.claude-3-5-sonnet-20241022-v2:0",
            info="Bedrock model ID",
        ),
        BoolInput(
            name="use_env_credentials",
            display_name="Use Environment Variables",
            value=True,
            info="Use AWS credentials from environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)",
            advanced=False,
        ),
        SecretStrInput(
            name="aws_access_key_id",
            display_name="AWS Access Key ID",
            info="Leave empty to use environment variable AWS_ACCESS_KEY_ID",
            required=False,
        ),
        SecretStrInput(
            name="aws_secret_access_key",
            display_name="AWS Secret Access Key",
            info="Leave empty to use environment variable AWS_SECRET_ACCESS_KEY",
            required=False,
        ),
        SecretStrInput(
            name="aws_session_token",
            display_name="AWS Session Token",
            advanced=True,
            info="Optional session token for temporary credentials. Leave empty to use AWS_SESSION_TOKEN env var",
            required=False,
        ),
        SecretStrInput(
            name="credentials_profile_name",
            display_name="Credentials Profile Name",
            advanced=True,
            info="AWS profile name from ~/.aws/credentials (optional)",
            required=False,
        ),
        DropdownInput(
            name="region_name",
            display_name="Region Name",
            value="us-east-1",
            options=[
                "us-east-1",
                "us-west-2",
                "ap-northeast-1",
                "ap-southeast-1",
                "eu-west-1",
                "eu-central-1",
            ],
            info="AWS region for Bedrock",
        ),
        MessageTextInput(
            name="endpoint_url",
            display_name="Endpoint URL",
            advanced=True,
            info="Custom Bedrock endpoint URL (optional)",
        ),
        # Model-specific parameters
        FloatInput(
            name="temperature",
            display_name="Temperature",
            value=0.7,
            info="Controls randomness in output. Higher values make output more random.",
            advanced=True,
        ),
        IntInput(
            name="max_tokens",
            display_name="Max Tokens",
            value=4096,
            info="Maximum number of tokens to generate.",
            advanced=True,
        ),
        FloatInput(
            name="top_p",
            display_name="Top P",
            value=0.9,
            info="Nucleus sampling parameter. Controls diversity of output.",
            advanced=True,
        ),
        IntInput(
            name="top_k",
            display_name="Top K",
            value=250,
            info="Limits the number of highest probability vocabulary tokens to consider.",
            advanced=True,
        ),
        BoolInput(
            name="disable_streaming",
            display_name="Disable Streaming",
            value=False,
            info="If True, disables streaming responses. Useful for batch processing.",
            advanced=True,
        ),
        DictInput(
            name="additional_model_fields",
            display_name="Additional Model Fields",
            advanced=True,
            is_list=True,
            info="Additional model-specific parameters for fine-tuning behavior.",
        ),
    ]

    def _get_credentials(self):
        """환경변수에서 안전하게 credentials를 가져옵니다."""
        if self.use_env_credentials:
            # 환경변수에서 읽기
            access_key = os.getenv("AWS_ACCESS_KEY_ID")
            secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
            session_token = os.getenv("AWS_SESSION_TOKEN")

            self.log("Using AWS credentials from environment variables")

            return {
                "aws_access_key_id": access_key,
                "aws_secret_access_key": secret_key,
                "aws_session_token": session_token,
            }
        else:
            # 사용자 입력에서 읽기
            if self.aws_access_key_id or self.aws_secret_access_key:
                self.log("Using AWS credentials from component inputs")
                return {
                    "aws_access_key_id": self.aws_access_key_id,
                    "aws_secret_access_key": self.aws_secret_access_key,
                    "aws_session_token": self.aws_session_token,
                }

        return {}

    def build_model(self) -> LanguageModel:
        try:
            from langchain_aws.chat_models.bedrock_converse import ChatBedrockConverse
        except ImportError as e:
            msg = "langchain_aws is not installed. Please install it with `pip install langchain_aws`."
            raise ImportError(msg) from e

        try:
            import boto3
        except ImportError as e:
            msg = "boto3 is not installed. Please install it with `pip install boto3`."
            raise ImportError(msg) from e

        # Credentials 가져오기
        credentials = self._get_credentials()

        # Session 생성
        if credentials and (credentials.get("aws_access_key_id") or credentials.get("aws_secret_access_key")):
            # 명시적 credentials 사용
            session = boto3.Session(**{k: v for k, v in credentials.items() if v})
            self.log("Created boto3 session with explicit credentials")
        elif self.credentials_profile_name:
            # AWS profile 사용
            session = boto3.Session(profile_name=self.credentials_profile_name)
            self.log(f"Created boto3 session with profile: {self.credentials_profile_name}")
        else:
            # Default credentials chain 사용
            session = boto3.Session()
            self.log("Created boto3 session with default credentials chain")

        # Client parameters
        client_params = {}
        if self.endpoint_url:
            client_params["endpoint_url"] = self.endpoint_url
        if self.region_name:
            client_params["region_name"] = self.region_name

        try:
            boto3_client = session.client("bedrock-runtime", **client_params)
            self.log(f"Created Bedrock client for region: {self.region_name}")
        except Exception as e:
            error_msg = f"Failed to create Bedrock client: {str(e)}"
            self.log(error_msg)
            raise RuntimeError(error_msg) from e

        # Prepare initialization parameters
        init_params = {
            "model": self.model_id,
            "client": boto3_client,
            "region_name": self.region_name,
        }

        # Add endpoint URL if provided
        if self.endpoint_url:
            init_params["endpoint_url"] = self.endpoint_url

        # Add model parameters
        if hasattr(self, "temperature") and self.temperature is not None:
            init_params["temperature"] = self.temperature
        if hasattr(self, "max_tokens") and self.max_tokens is not None:
            init_params["max_tokens"] = self.max_tokens
        if hasattr(self, "top_p") and self.top_p is not None:
            init_params["top_p"] = self.top_p

        # Handle streaming
        if hasattr(self, "disable_streaming") and self.disable_streaming:
            init_params["disable_streaming"] = True

        # Handle additional model request fields
        additional_model_request_fields = {}

        if hasattr(self, "additional_model_fields") and self.additional_model_fields:
            for field in self.additional_model_fields:
                if isinstance(field, dict):
                    additional_model_request_fields.update(field)

        if additional_model_request_fields:
            init_params["additional_model_request_fields"] = additional_model_request_fields

        try:
            output = ChatBedrockConverse(**init_params)
            self.log(f"Created ChatBedrockConverse with model: {self.model_id}")
            return output
        except Exception as e:
            error_details = str(e)
            if "validation error" in error_details.lower():
                msg = (
                    f"ChatBedrockConverse validation error: {error_details}. "
                    f"This may be due to incompatible parameters for model '{self.model_id}'. "
                    f"Consider adjusting the model parameters."
                )
            elif "converse api" in error_details.lower():
                msg = (
                    f"Converse API error: {error_details}. "
                    f"The model '{self.model_id}' may not support the Converse API."
                )
            else:
                msg = f"Could not initialize ChatBedrockConverse: {error_details}"
            self.log(msg)
            raise ValueError(msg) from e
