import os

from lfx.base.models.model import LCModelComponent
from lfx.field_typing import Embeddings
from lfx.inputs.inputs import SecretStrInput
from lfx.io import BoolInput, DropdownInput, MessageTextInput, Output


class AmazonBedrockEmbeddingsComponent(LCModelComponent):
    """Amazon Bedrock Embeddings with secure credential handling."""

    display_name: str = "Amazon Bedrock Embeddings (Secure)"
    description: str = "Generate embeddings using Amazon Bedrock models with environment variable support."
    icon = "Amazon"
    name = "AmazonBedrockEmbeddingsSecure"

    inputs = [
        DropdownInput(
            name="model_id",
            display_name="Model ID",
            options=[
                "cohere.embed-english-v3",
                "cohere.embed-multilingual-v3",
                "amazon.titan-embed-text-v1",
                "amazon.titan-embed-text-v2:0",
            ],
            value="cohere.embed-multilingual-v3",
            info="Bedrock embedding model ID",
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
    ]

    outputs = [
        Output(display_name="Embeddings", name="embeddings", method="build_embeddings"),
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

    def build_embeddings(self) -> Embeddings:
        try:
            from langchain_aws import BedrockEmbeddings
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
        if credentials:
            # 명시적 credentials 사용
            session = boto3.Session(**credentials)
            self.log("Created boto3 session with explicit credentials")
        elif self.credentials_profile_name:
            # AWS profile 사용
            session = boto3.Session(profile_name=self.credentials_profile_name)
            self.log(f"Created boto3 session with profile: {self.credentials_profile_name}")
        else:
            # Default credentials chain 사용 (IAM role, instance profile 등)
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

        try:
            embeddings = BedrockEmbeddings(
                client=boto3_client,
                model_id=self.model_id,
                region_name=self.region_name,
            )
            self.log(f"Created BedrockEmbeddings with model: {self.model_id}")
            return embeddings
        except Exception as e:
            error_msg = f"Failed to create BedrockEmbeddings: {str(e)}"
            self.log(error_msg)
            raise RuntimeError(error_msg) from e
