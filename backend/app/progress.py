"""Request-scoped, safe recovery progress events for the live demo UI."""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from threading import RLock
from typing import Any

from pydantic import Field

from app.models import ContractModel

MAX_PROGRESS_EVENTS = 256
_PROGRESS_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
_CURRENT_PROGRESS_ID: ContextVar[str | None] = ContextVar("daymend_progress_id", default=None)


class ProgressActorType(StrEnum):
    AGENT = "AGENT"
    DETERMINISTIC_SERVICE = "DETERMINISTIC_SERVICE"
    HUMAN = "HUMAN"
    SYSTEM = "SYSTEM"


class ProgressStatus(StrEnum):
    WAITING = "WAITING"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    WARNING = "WARNING"
    FAILED = "FAILED"


class RecoveryProgressEvent(ContractModel):
    """One ordered event containing only reviewed, structured progress metadata."""

    id: str
    progress_id: str
    recovery_case_id: str | None = None
    sequence: int = Field(ge=1)
    timestamp: datetime
    event_type: str
    actor_type: ProgressActorType
    actor_name: str
    stage: str
    status: ProgressStatus
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)


@dataclass
class _ProgressChannel:
    progress_id: str
    recovery_case_id: str | None = None
    events: list[RecoveryProgressEvent] = field(default_factory=list)
    next_sequence: int = 1


class RecoveryProgressBuffer:
    """Thread-safe in-memory channels addressable by progress ID or case ID."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._channels: dict[str, _ProgressChannel] = {}

    def start(self, progress_id: str, *, recovery_case_id: str | None = None) -> None:
        _validate_progress_id(progress_id)
        with self._lock:
            case_channel = (
                self._channels.get(recovery_case_id) if recovery_case_id is not None else None
            )
            channel = case_channel or self._channels.get(progress_id)
            if channel is None:
                channel = _ProgressChannel(progress_id=progress_id)
            self._channels[progress_id] = channel
            if recovery_case_id is not None:
                self._attach_locked(channel, recovery_case_id)

    def append(
        self,
        progress_id: str,
        *,
        recovery_case_id: str | None,
        event_type: str,
        actor_type: ProgressActorType,
        actor_name: str,
        stage: str,
        status: ProgressStatus,
        summary: str,
        details: dict[str, Any] | None = None,
    ) -> RecoveryProgressEvent:
        _validate_progress_id(progress_id)
        with self._lock:
            channel = self._channels.get(progress_id)
            if channel is None:
                channel = _ProgressChannel(progress_id=progress_id)
                self._channels[progress_id] = channel
            if recovery_case_id is not None:
                self._attach_locked(channel, recovery_case_id)
            sequence = channel.next_sequence
            channel.next_sequence += 1
            event = RecoveryProgressEvent(
                id=f"{channel.progress_id}:{sequence}",
                progress_id=channel.progress_id,
                recovery_case_id=channel.recovery_case_id,
                sequence=sequence,
                timestamp=datetime.now(UTC),
                event_type=event_type,
                actor_type=actor_type,
                actor_name=actor_name,
                stage=stage,
                status=status,
                summary=summary,
                details=details or {},
            )
            channel.events.append(event)
            if len(channel.events) > MAX_PROGRESS_EVENTS:
                del channel.events[: len(channel.events) - MAX_PROGRESS_EVENTS]
            return event

    def snapshot(self, progress_or_case_id: str) -> list[RecoveryProgressEvent]:
        _validate_progress_id(progress_or_case_id)
        with self._lock:
            channel = self._channels.get(progress_or_case_id)
            return list(channel.events) if channel is not None else []

    def after(self, progress_or_case_id: str, sequence: int) -> list[RecoveryProgressEvent]:
        return [event for event in self.snapshot(progress_or_case_id) if event.sequence > sequence]

    def clear(self) -> None:
        with self._lock:
            self._channels.clear()

    def _attach_locked(self, channel: _ProgressChannel, recovery_case_id: str) -> None:
        existing = self._channels.get(recovery_case_id)
        if existing is not None and existing is not channel:
            return
        channel.recovery_case_id = recovery_case_id
        self._channels[recovery_case_id] = channel


progress_buffer = RecoveryProgressBuffer()


@contextmanager
def progress_scope(
    progress_id: str,
    *,
    recovery_case_id: str | None = None,
) -> Iterator[None]:
    """Bind structured logs from one synchronous request to its progress channel."""

    progress_buffer.start(progress_id, recovery_case_id=recovery_case_id)
    token = _CURRENT_PROGRESS_ID.set(progress_id)
    try:
        yield
    finally:
        _CURRENT_PROGRESS_ID.reset(token)


def emit_progress_from_log(event_type: str, fields: dict[str, Any]) -> None:
    """Translate reviewed application log events into safe user-facing progress events."""

    progress_id = _CURRENT_PROGRESS_ID.get()
    if progress_id is None:
        return
    for presentation in _presentations(event_type, fields):
        progress_buffer.append(
            progress_id,
            recovery_case_id=_optional_string(fields.get("recovery_case_id")),
            details=_safe_details(fields),
            **presentation,
        )


_DETAIL_FIELDS = {
    "action_id",
    "action_type",
    "affected_windows",
    "attempt_number",
    "candidate_count",
    "cost",
    "eligible_candidate_count",
    "invalidated_count",
    "issue_codes",
    "issue_count",
    "operation",
    "orchestrator_invocation_count",
    "plan_id",
    "planner_invocation_count",
    "preserved_count",
    "recommended_candidate_id",
    "research_agent_invocation_count",
    "requires_approval",
    "retry_number",
    "success",
}


def _safe_details(fields: dict[str, Any]) -> dict[str, Any]:
    return {key: fields[key] for key in _DETAIL_FIELDS if fields.get(key) is not None}


def _presentations(event_type: str, fields: dict[str, Any]) -> list[dict[str, Any]]:
    stage = _stage(fields)
    fixed: dict[str, tuple[str, ProgressActorType, str, ProgressStatus, str]] = {
        "recovery_started": (
            "RECOVERY_STARTED",
            ProgressActorType.SYSTEM,
            "daymend",
            ProgressStatus.COMPLETED,
            "Recovery case started",
        ),
        "planning_started": (
            "ORCHESTRATOR_STARTED",
            ProgressActorType.AGENT,
            "recovery_orchestrator",
            ProgressStatus.ACTIVE,
            "Coordinating the recovery",
        ),
        "agentcore_invocation_started": (
            "ORCHESTRATOR_STARTED",
            ProgressActorType.AGENT,
            "recovery_orchestrator",
            ProgressStatus.ACTIVE,
            "AgentCore reasoning request started",
        ),
        "agentcore_invocation_completed": (
            "DISRUPTION_ASSESSED",
            ProgressActorType.AGENT,
            "recovery_orchestrator",
            ProgressStatus.COMPLETED,
            "Structured recovery context returned",
        ),
        "agentcore_invocation_failed": (
            "AGENTCORE_FAILED",
            ProgressActorType.AGENT,
            "recovery_orchestrator",
            ProgressStatus.FAILED,
            "AgentCore reasoning request failed safely",
        ),
        "agentcore_transport_retry": (
            "AGENTCORE_TRANSPORT_RETRY",
            ProgressActorType.AGENT,
            "recovery_orchestrator",
            ProgressStatus.WARNING,
            "Reasoning runtime connection interrupted — reconnecting",
        ),
        "orchestrator_invocation_started": (
            "ORCHESTRATOR_STARTED",
            ProgressActorType.AGENT,
            "recovery_orchestrator",
            ProgressStatus.ACTIVE,
            "Understanding the disruption and constraints",
        ),
        "orchestrator_invocation_completed": (
            "DISRUPTION_ASSESSED",
            ProgressActorType.AGENT,
            "recovery_orchestrator",
            ProgressStatus.COMPLETED,
            "Planning brief completed",
        ),
        "planner_invocation_started": (
            "PLANNER_STARTED",
            ProgressActorType.AGENT,
            "constraint_planner",
            ProgressStatus.ACTIVE,
            "Building a complete recovery plan",
        ),
        "planner_attempt_started": (
            "PLANNER_STARTED",
            ProgressActorType.AGENT,
            "constraint_planner",
            ProgressStatus.ACTIVE,
            "Building a plan proposal",
        ),
        "planner_attempt_completed": (
            "PLAN_PROPOSED",
            ProgressActorType.AGENT,
            "constraint_planner",
            ProgressStatus.COMPLETED,
            "Plan proposal received",
        ),
        "plan_proposed": (
            "PLAN_PROPOSED",
            ProgressActorType.AGENT,
            "constraint_planner",
            ProgressStatus.COMPLETED,
            "Plan proposal received",
        ),
        "validation_started": (
            "VALIDATION_STARTED",
            ProgressActorType.DETERMINISTIC_SERVICE,
            "plan_validator",
            ProgressStatus.ACTIVE,
            "Checking coverage, calendars, travel, and policy",
        ),
        "planner_validation_failed": (
            "VALIDATION_FAILED",
            ProgressActorType.DETERMINISTIC_SERVICE,
            "plan_validator",
            ProgressStatus.WARNING,
            "Plan needs deterministic repair",
        ),
        "planner_validation_succeeded": (
            "VALIDATION_PASSED",
            ProgressActorType.DETERMINISTIC_SERVICE,
            "plan_validator",
            ProgressStatus.COMPLETED,
            "Plan passed deterministic validation",
        ),
        "plan_repair_started": (
            "PLAN_REPAIR_STARTED",
            ProgressActorType.AGENT,
            "constraint_planner",
            ProgressStatus.ACTIVE,
            "Repairing every listed validation issue",
        ),
        "planning_validated": (
            "PLAN_A_ACCEPTED",
            ProgressActorType.AGENT,
            "recovery_orchestrator",
            ProgressStatus.COMPLETED,
            "Plan A accepted",
        ),
        "caregiver_declined": (
            "WORLD_STATE_CHANGED",
            ProgressActorType.SYSTEM,
            "world_state",
            ProgressStatus.WARNING,
            "Grandma can no longer cover her assigned segments",
        ),
        "replanning_started": (
            "REPLANNING_STARTED",
            ProgressActorType.AGENT,
            "recovery_orchestrator",
            ProgressStatus.ACTIVE,
            "Replanning only the affected coverage",
        ),
        "assumption_invalidated": (
            "SEGMENTS_INVALIDATED",
            ProgressActorType.DETERMINISTIC_SERVICE,
            "plan_invalidation",
            ProgressStatus.WARNING,
            "Dependent coverage invalidated",
        ),
        "backup_research_started": (
            "RESEARCH_STARTED",
            ProgressActorType.AGENT,
            "backup_care_research",
            ProgressStatus.ACTIVE,
            "Searching eligible backup-care options",
        ),
        "known_options_exhausted": (
            "KNOWN_OPTIONS_EXHAUSTED",
            ProgressActorType.DETERMINISTIC_SERVICE,
            "plan_validator",
            ProgressStatus.WARNING,
            "Known options cannot cover the affected window",
        ),
        "backup_candidates_received": (
            "RESEARCH_RESULTS_READY",
            ProgressActorType.AGENT,
            "backup_care_research",
            ProgressStatus.COMPLETED,
            "Eligible backup-care results received",
        ),
        "backup_candidate_recommended": (
            "BACKUP_SELECTED",
            ProgressActorType.AGENT,
            "backup_care_research",
            ProgressStatus.COMPLETED,
            "Grounded replacement recommended",
        ),
        "approval_requested": (
            "APPROVAL_REQUIRED",
            ProgressActorType.DETERMINISTIC_SERVICE,
            "deterministic_policy",
            ProgressStatus.WARNING,
            "Human approval required before execution",
        ),
        "execution_started": (
            "EXECUTION_STARTED",
            ProgressActorType.DETERMINISTIC_SERVICE,
            "execution_service",
            ProgressStatus.ACTIVE,
            "Executing the approved recovery plan",
        ),
        "recovery_resolved": (
            "RECOVERY_RESOLVED",
            ProgressActorType.SYSTEM,
            "daymend",
            ProgressStatus.COMPLETED,
            "Recovery resolved",
        ),
        "recovery_failed": (
            "RECOVERY_FAILED",
            ProgressActorType.SYSTEM,
            "daymend",
            ProgressStatus.FAILED,
            "Recovery could not be completed safely",
        ),
    }
    if event_type == "replan_validated":
        events = []
        if fields.get("preserved_count") is not None:
            events.append(
                _presentation(
                    "SEGMENTS_PRESERVED",
                    ProgressActorType.DETERMINISTIC_SERVICE,
                    "plan_invalidation",
                    ProgressStatus.COMPLETED,
                    "Still-valid Plan A segments preserved",
                    stage,
                )
            )
        events.append(
            _presentation(
                "PLAN_B_ACCEPTED",
                ProgressActorType.AGENT,
                "recovery_orchestrator",
                ProgressStatus.COMPLETED,
                "Plan B accepted",
                stage,
            )
        )
        return events
    if event_type == "execution_action_completed":
        succeeded = fields.get("success") is True
        return [
            _presentation(
                "ACTION_SUCCEEDED" if succeeded else "ACTION_FAILED",
                ProgressActorType.DETERMINISTIC_SERVICE,
                "execution_service",
                ProgressStatus.COMPLETED if succeeded else ProgressStatus.FAILED,
                "Recovery action completed" if succeeded else "Recovery action failed",
                stage,
            )
        ]
    if event_type == "completion_verified":
        succeeded = fields.get("success") is True
        return [
            _presentation(
                "COMPLETION_VERIFIED",
                ProgressActorType.DETERMINISTIC_SERVICE,
                "completion_verifier",
                ProgressStatus.COMPLETED if succeeded else ProgressStatus.FAILED,
                (
                    "Final childcare coverage verified"
                    if succeeded
                    else "Final coverage verification failed"
                ),
                stage,
            )
        ]
    if event_type == "approval_decision":
        approved = str(fields.get("decision")) == "APPROVE"
        return [
            _presentation(
                "APPROVAL_APPROVED" if approved else "APPROVAL_REJECTED",
                ProgressActorType.HUMAN,
                "user",
                ProgressStatus.COMPLETED if approved else ProgressStatus.WARNING,
                "Recovery approved" if approved else "Recovery rejected; nothing executed",
                stage,
            )
        ]
    item = fixed.get(event_type)
    if item is None:
        return []
    return [_presentation(*item, stage)]


def _presentation(
    event_type: str,
    actor_type: ProgressActorType,
    actor_name: str,
    status: ProgressStatus,
    summary: str,
    stage: str,
) -> dict[str, Any]:
    return {
        "event_type": event_type,
        "actor_type": actor_type,
        "actor_name": actor_name,
        "stage": stage,
        "status": status,
        "summary": summary,
    }


def _stage(fields: dict[str, Any]) -> str:
    if fields.get("operation") == "PLAN_REPAIR":
        return "PLAN_REPAIR"
    value = str(fields.get("phase") or fields.get("planning_mode") or "recovery")
    if value in {"initial", "initial_planning"}:
        return "PLAN_A"
    if value in {"replanning", "repair"}:
        return "PLAN_B"
    return value.upper()


def _optional_string(value: Any) -> str | None:
    return str(value) if value is not None else None


def _validate_progress_id(progress_id: str) -> None:
    if not _PROGRESS_ID_PATTERN.fullmatch(progress_id):
        raise ValueError("progress ID must be 8-128 safe identifier characters")
