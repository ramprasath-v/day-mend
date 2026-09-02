"""Environment-backed configuration for the Bedrock model used by Strands."""

import os
from dataclasses import dataclass
from enum import StrEnum

DEFAULT_BEDROCK_MODEL_ID = "global.anthropic.claude-sonnet-4-6"


class AgentArchitecture(StrEnum):
    """Selectable reasoning architecture while the multi-agent path is proven locally."""

    SINGLE = "single"
    MULTI = "multi"
    MULTI_RESEARCH = "multi_research"


@dataclass(frozen=True)
class RecoveryAgentConfig:
    """Configuration resolved without embedding or logging AWS credentials."""

    model_id: str
    region_name: str | None
    architecture: AgentArchitecture = AgentArchitecture.SINGLE

    @classmethod
    def from_environment(cls) -> "RecoveryAgentConfig":
        """Resolve model and region while leaving credentials to the AWS SDK chain."""

        architecture = os.getenv("DAYMEND_AGENT_ARCHITECTURE", AgentArchitecture.SINGLE).strip()
        try:
            resolved_architecture = AgentArchitecture(architecture.lower())
        except ValueError as exc:
            raise ValueError(
                "DAYMEND_AGENT_ARCHITECTURE must be 'single', 'multi', or 'multi_research'"
            ) from exc
        return cls(
            model_id=os.getenv("DAYMEND_BEDROCK_MODEL_ID", DEFAULT_BEDROCK_MODEL_ID),
            region_name=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION"),
            architecture=resolved_architecture,
        )
