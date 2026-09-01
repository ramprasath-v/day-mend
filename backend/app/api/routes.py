"""Thin FastAPI routes for the DayMend recovery lifecycle."""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.dependencies import get_application_service
from app.api.mappers import recovery_case_response
from app.api.models import (
    ApprovalDecisionRequest,
    CreateRecoveryRequest,
    ExternalRecoveryEventRequest,
    HealthResponse,
    RecoveryCaseResponse,
)
from app.application import (
    ApprovalCommand,
    EventCommand,
    RecoveryApplicationService,
    StartRecoveryCommand,
)
from app.models import CoverageWindow

router = APIRouter()
Service = Annotated[RecoveryApplicationService, Depends(get_application_service)]


@router.get("/health", response_model=HealthResponse, summary="Check API health")
def health() -> HealthResponse:
    """Return process health without contacting Bedrock or DynamoDB."""

    return HealthResponse()


@router.post(
    "/recoveries",
    response_model=RecoveryCaseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start childcare disruption recovery",
)
def create_recovery(request: CreateRecoveryRequest, service: Service) -> RecoveryCaseResponse:
    recovery_case = service.start_recovery(
        StartRecoveryCommand(
            disruption_type=request.disruption_type,
            occurred_at=request.occurred_at,
            caregiver_id=request.caregiver_id,
            message=request.message,
        )
    )
    return recovery_case_response(recovery_case)


@router.get(
    "/recoveries/{recovery_case_id}",
    response_model=RecoveryCaseResponse,
    summary="Get current recovery state",
)
def get_recovery(recovery_case_id: str, service: Service) -> RecoveryCaseResponse:
    return recovery_case_response(service.get_recovery(recovery_case_id))


@router.post(
    "/recoveries/{recovery_case_id}/events",
    response_model=RecoveryCaseResponse,
    summary="Apply an external world-state event",
)
def add_recovery_event(
    recovery_case_id: str,
    request: ExternalRecoveryEventRequest,
    service: Service,
) -> RecoveryCaseResponse:
    updated = service.process_event(
        recovery_case_id,
        EventCommand(
            event_type=request.event_type,
            caregiver_id=request.caregiver_id,
            occurred_at=request.occurred_at,
            relevant_window=CoverageWindow(
                start=request.relevant_window.start,
                end=request.relevant_window.end,
            ),
            message=request.message,
            event_id=request.event_id,
            expected_version=request.expected_version,
        ),
    )
    return recovery_case_response(updated)


@router.post(
    "/recoveries/{recovery_case_id}/approvals/{approval_id}",
    response_model=RecoveryCaseResponse,
    summary="Approve or reject the pending recovery action",
)
def decide_approval(
    recovery_case_id: str,
    approval_id: str,
    request: ApprovalDecisionRequest,
    service: Service,
) -> RecoveryCaseResponse:
    updated = service.decide_approval(
        recovery_case_id,
        approval_id,
        ApprovalCommand(
            decision=request.decision,
            reason=request.reason,
            expected_version=request.expected_version,
        ),
    )
    return recovery_case_response(updated)
