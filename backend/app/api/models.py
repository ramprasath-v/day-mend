"""Stable, frontend-friendly HTTP contracts for the DayMend API."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.application import ApprovalDecision
from app.models import (
    ApprovalStatus,
    ApprovalType,
    CoverageSource,
    ExecutionActionStatus,
    ExecutionActionType,
    PlanAssumptionStatus,
    PlanValidationState,
    RecoveryEventType,
    RecoveryStatus,
)


class ApiModel(BaseModel):
    """Strict API contract base."""

    model_config = ConfigDict(extra="forbid")


class CoverageWindowRequest(ApiModel):
    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode="after")
    def end_must_follow_start(self) -> "CoverageWindowRequest":
        if self.end <= self.start:
            raise ValueError("end must be after start")
        return self


class CreateRecoveryRequest(ApiModel):
    disruption_type: Literal["CHILDCARE_UNAVAILABLE"]
    occurred_at: AwareDatetime
    caregiver_id: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=1000)


class ExternalRecoveryEventRequest(ApiModel):
    event_type: Literal[RecoveryEventType.CAREGIVER_DECLINED]
    caregiver_id: str = Field(min_length=1)
    occurred_at: AwareDatetime
    relevant_window: CoverageWindowRequest
    message: str = Field(min_length=1, max_length=1000)
    event_id: str | None = Field(default=None, min_length=1)
    expected_version: int | None = Field(default=None, ge=1)


class ApprovalDecisionRequest(ApiModel):
    decision: ApprovalDecision
    reason: str | None = Field(default=None, max_length=1000)
    expected_version: int | None = Field(default=None, ge=1)


class DisruptionResponse(ApiModel):
    disruption_type: str
    occurred_at: datetime
    caregiver_id: str
    message: str


class CoverageWindowResponse(ApiModel):
    start: datetime
    end: datetime


class CoverageSegmentResponse(ApiModel):
    segment_id: str
    window: CoverageWindowResponse
    assigned_person_id: str
    source: CoverageSource
    segment_type: str
    location_id: str
    location_label: str
    destination_location_id: str | None
    destination_location_label: str | None
    transporter_id: str | None
    estimated_cost: Decimal


class CalendarChangeResponse(ApiModel):
    event_id: str
    owner_id: str
    title: str
    window: CoverageWindowResponse
    location: str | None


class AssumptionResponse(ApiModel):
    assumption_id: str
    assumption_type: str
    subject_id: str
    relevant_window: CoverageWindowResponse | None
    status: PlanAssumptionStatus
    invalidated_at: datetime | None
    invalidation_reason: str | None
    triggering_event_id: str | None


class RecoveryPlanResponse(ApiModel):
    plan_id: str
    coverage_segments: list[CoverageSegmentResponse]
    calendar_changes: list[CalendarChangeResponse]
    estimated_cost: Decimal
    validation_state: PlanValidationState
    validation_errors: list[str]


class RecoveryPlanSummaryResponse(ApiModel):
    plan_id: str
    validation_state: PlanValidationState
    estimated_cost: Decimal
    coverage_segment_count: int


class RecoveryEventResponse(ApiModel):
    event_id: str
    event_type: RecoveryEventType
    occurred_at: datetime
    caregiver_id: str | None
    relevant_window: CoverageWindowResponse | None
    message: str | None
    details: dict[str, Any]


class ApprovalResponse(ApiModel):
    approval_id: str
    approval_type: ApprovalType
    plan_id: str
    reason: str
    summary: str
    consequence: str
    requested_at: datetime
    status: ApprovalStatus
    amount: Decimal | None
    currency: str | None
    decided_at: datetime | None


class ExecutionActionResponse(ApiModel):
    action_id: str
    action_type: ExecutionActionType
    target_id: str
    plan_id: str
    status: ExecutionActionStatus
    attempted_at: datetime
    completed_at: datetime | None
    result: str | None
    error: str | None


class RecoveryTimestampsResponse(ApiModel):
    created_at: datetime
    updated_at: datetime
    completion_verified_at: datetime | None


class RecoveryCaseResponse(ApiModel):
    recovery_case_id: str
    status: RecoveryStatus
    original_disruption: DisruptionResponse
    active_plan: RecoveryPlanResponse | None
    plan_history: list[RecoveryPlanSummaryResponse]
    previous_plans: list[RecoveryPlanResponse]
    events: list[RecoveryEventResponse]
    invalidated_assumptions: list[AssumptionResponse]
    pending_approval: ApprovalResponse | None
    approval_history: list[ApprovalResponse]
    execution_actions: list[ExecutionActionResponse]
    current_deterministic_cost: Decimal
    requires_approval: bool
    automatic_spend_limit: Decimal | None
    currency: str | None
    latest_trigger: str | None
    timestamps: RecoveryTimestampsResponse
    version: int


class HealthResponse(ApiModel):
    status: Literal["ok"] = "ok"
    service: Literal["daymend-api"] = "daymend-api"


class ErrorDetail(ApiModel):
    code: str
    message: str


class ErrorResponse(ApiModel):
    error: ErrorDetail
