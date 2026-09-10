"""Thin FastAPI routes for the DayMend recovery lifecycle."""

import asyncio
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, Request, status
from fastapi.responses import StreamingResponse

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
from app.progress import RecoveryProgressEvent, progress_buffer, progress_scope

router = APIRouter()
Service = Annotated[RecoveryApplicationService, Depends(get_application_service)]
ProgressHeader = Annotated[str | None, Header(alias="X-DayMend-Progress-ID")]


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
def create_recovery(
    request: CreateRecoveryRequest,
    service: Service,
    progress_id: ProgressHeader = None,
) -> RecoveryCaseResponse:
    resolved_progress_id = progress_id or str(uuid4())
    with progress_scope(resolved_progress_id):
        recovery_case = service.start_recovery(
            StartRecoveryCommand(
                disruption_type=request.disruption_type,
                occurred_at=request.occurred_at,
                caregiver_id=request.caregiver_id,
                message=request.message,
            )
        )
    progress_buffer.start(
        resolved_progress_id,
        recovery_case_id=recovery_case.case_id,
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
    progress_id: ProgressHeader = None,
) -> RecoveryCaseResponse:
    resolved_progress_id = progress_id or recovery_case_id
    with progress_scope(resolved_progress_id, recovery_case_id=recovery_case_id):
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
    progress_id: ProgressHeader = None,
) -> RecoveryCaseResponse:
    resolved_progress_id = progress_id or recovery_case_id
    with progress_scope(resolved_progress_id, recovery_case_id=recovery_case_id):
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


@router.get(
    "/progress/{progress_id}",
    response_model=list[RecoveryProgressEvent],
    summary="Get a recovery progress snapshot",
)
def get_progress(progress_id: str) -> list[RecoveryProgressEvent]:
    return progress_buffer.snapshot(progress_id)


@router.get(
    "/recoveries/{recovery_case_id}/progress",
    response_model=list[RecoveryProgressEvent],
    summary="Get progress for an existing recovery case",
)
def get_recovery_progress(recovery_case_id: str) -> list[RecoveryProgressEvent]:
    return progress_buffer.snapshot(recovery_case_id)


@router.get(
    "/progress/{progress_id}/stream",
    summary="Stream ordered recovery progress events",
)
async def stream_progress(
    progress_id: str,
    request: Request,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    once: bool = False,
) -> StreamingResponse:
    progress_buffer.start(progress_id)
    try:
        cursor = int(last_event_id or 0)
    except ValueError:
        cursor = 0

    async def event_stream():
        nonlocal cursor
        while True:
            for event in progress_buffer.after(progress_id, cursor):
                cursor = event.sequence
                yield f"id: {event.sequence}\nevent: progress\ndata: {event.model_dump_json()}\n\n"
            if once or await request.is_disconnected():
                return
            yield ": keep-alive\n\n"
            await asyncio.sleep(0.75)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
