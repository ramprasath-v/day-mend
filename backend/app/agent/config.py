"""Environment-backed configuration for the Bedrock model used by Strands."""

import os
from dataclasses import dataclass

DEFAULT_BEDROCK_MODEL_ID = "global.anthropic.claude-sonnet-4-6"


@dataclass(frozen=True)
class RecoveryAgentConfig:
    """Configuration resolved without embedding or logging AWS credentials."""

    model_id: str
    region_name: str | None

    @classmethod
    def from_environment(cls) -> "RecoveryAgentConfig":
        """Resolve model and region while leaving credentials to the AWS SDK chain."""

        return cls(
            model_id=os.getenv("DAYMEND_BEDROCK_MODEL_ID", DEFAULT_BEDROCK_MODEL_ID),
            region_name=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION"),
        )
