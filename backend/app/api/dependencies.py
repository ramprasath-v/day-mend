"""Environment-driven dependency wiring for the FastAPI boundary."""

import os

from fastapi import Request

from app.agent.runtime_gateway import (
    AgentRuntimeMode,
    build_agentcore_gateway,
    runtime_mode_from_environment,
)
from app.application import RecoveryApplicationService, StrandsRecoveryPlanningGateway
from app.repositories import (
    DynamoDBRecoveryCaseRepository,
    InMemoryRecoveryCaseRepository,
    RecoveryCaseRepository,
)


def build_recovery_repository() -> RecoveryCaseRepository:
    """Select persistence explicitly without embedding AWS settings in routes."""

    backend = os.getenv("DAYMEND_RECOVERY_REPOSITORY", "memory").strip().lower()
    if backend == "memory":
        return InMemoryRecoveryCaseRepository()
    if backend == "dynamodb":
        return DynamoDBRecoveryCaseRepository()
    raise ValueError("DAYMEND_RECOVERY_REPOSITORY must be 'memory' or 'dynamodb'")


def build_application_service() -> RecoveryApplicationService:
    planning_gateway = (
        build_agentcore_gateway()
        if runtime_mode_from_environment() is AgentRuntimeMode.AGENTCORE
        else StrandsRecoveryPlanningGateway()
    )
    return RecoveryApplicationService(
        build_recovery_repository(),
        planning_gateway,
    )


def get_application_service(request: Request) -> RecoveryApplicationService:
    return request.app.state.recovery_service


def allowed_origins() -> list[str]:
    raw = os.getenv("DAYMEND_ALLOWED_ORIGINS", "http://localhost:4200")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]
