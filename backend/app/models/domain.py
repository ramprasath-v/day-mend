"""Initial DayMend domain contracts.

These models describe recovery state without implementing planning, validation,
execution, persistence, or API behavior.
"""

from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class ContractModel(BaseModel):
    """Shared strict configuration for domain contracts."""

    model_config = ConfigDict(extra="forbid")


class RecoveryStatus(StrEnum):
    """Lifecycle states for a persistent recovery case."""

    DETECTED = "DETECTED"
    ASSESSING = "ASSESSING"
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    WAITING_FOR_RESPONSE = "WAITING_FOR_RESPONSE"
    REPLANNING = "REPLANNING"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    RESOLVED = "RESOLVED"
    FAILED = "FAILED"


class PlanAssumptionStatus(StrEnum):
    """Whether an assumption may still support an active plan."""

    ACTIVE = "ACTIVE"
    INVALIDATED = "INVALIDATED"


class PlanValidationState(StrEnum):
    """Result of deterministic plan validation."""

    PENDING = "PENDING"
    VALID = "VALID"
    INVALID = "INVALID"


class ApprovalStatus(StrEnum):
    """Decision state for an autonomy-boundary request."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class CoverageWindow(ContractModel):
    """A timezone-aware interval during which childcare is needed or available."""

    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode="after")
    def end_must_follow_start(self) -> "CoverageWindow":
        if self.end <= self.start:
            raise ValueError("end must be after start")
        return self


class CalendarEvent(ContractModel):
    """A parent calendar commitment that may constrain a recovery plan."""

    event_id: str
    owner_id: str
    title: str
    window: CoverageWindow
    location: str | None = None
    movable: bool = False


class Caregiver(ContractModel):
    """A potential caregiver and the known facts relevant to recovery."""

    caregiver_id: str
    name: str
    trusted: bool
    relationship: str | None = None
    availability: list[CoverageWindow] = Field(default_factory=list)
    hourly_rate: Decimal | None = Field(default=None, ge=0)


class FamilyPolicy(ContractModel):
    """Family preferences and deterministic autonomy boundaries."""

    trusted_caregiver_ids: set[str] = Field(default_factory=set)
    automatic_spend_limit: Decimal = Field(default=Decimal("0"), ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    minimum_handoff_minutes: int = Field(default=0, ge=0)
    preferences: dict[str, Any] = Field(default_factory=dict)


class RecoveryPlanSegment(ContractModel):
    """One continuous portion of childcare coverage in a proposed plan."""

    segment_id: str
    window: CoverageWindow
    assigned_caregiver_id: str
    source: str
    estimated_cost: Decimal = Field(default=Decimal("0"), ge=0)


class PlanAssumption(ContractModel):
    """A world-state claim on which a plan depends."""

    assumption_id: str
    assumption_type: str
    subject_id: str
    relevant_window: CoverageWindow | None = None
    value: Any | None = None
    status: PlanAssumptionStatus = PlanAssumptionStatus.ACTIVE
    invalidated_at: AwareDatetime | None = None
    invalidation_reason: str | None = None

    @model_validator(mode="after")
    def invalidation_details_match_status(self) -> "PlanAssumption":
        if self.status is PlanAssumptionStatus.ACTIVE and (
            self.invalidated_at is not None or self.invalidation_reason is not None
        ):
            raise ValueError("active assumptions cannot have invalidation details")
        if self.status is PlanAssumptionStatus.INVALIDATED and self.invalidated_at is None:
            raise ValueError("invalidated assumptions require invalidated_at")
        return self


class RecoveryPlan(ContractModel):
    """A structured recovery proposal awaiting or carrying validation state."""

    plan_id: str
    coverage_segments: list[RecoveryPlanSegment] = Field(default_factory=list)
    calendar_changes: list[CalendarEvent] = Field(default_factory=list)
    estimated_cost: Decimal = Field(default=Decimal("0"), ge=0)
    assumptions: list[PlanAssumption] = Field(default_factory=list)
    validation_state: PlanValidationState = PlanValidationState.PENDING
    validation_errors: list[str] = Field(default_factory=list)


class ApprovalRequest(ContractModel):
    """A meaningful decision that must be made by the parent."""

    approval_id: str
    reason: str
    requested_at: AwareDatetime
    status: ApprovalStatus = ApprovalStatus.PENDING
    amount: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    decided_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def decision_time_matches_status(self) -> "ApprovalRequest":
        if self.status is ApprovalStatus.PENDING and self.decided_at is not None:
            raise ValueError("pending approval requests cannot have decided_at")
        if self.status is not ApprovalStatus.PENDING and self.decided_at is None:
            raise ValueError("decided approval requests require decided_at")
        return self


class RecoveryEvent(ContractModel):
    """An immutable-style fact recorded in a recovery case history."""

    event_id: str
    event_type: str
    occurred_at: AwareDatetime
    details: dict[str, Any] = Field(default_factory=dict)


class RecoveryCase(ContractModel):
    """Persistent aggregate for a childcare disruption and its recovery history."""

    case_id: str
    status: RecoveryStatus = RecoveryStatus.DETECTED
    disruption: str
    coverage_gap: CoverageWindow
    context_state: dict[str, Any] = Field(default_factory=dict)
    active_recovery_plan: RecoveryPlan | None = None
    previous_plans: list[RecoveryPlan] = Field(default_factory=list)
    assumptions: list[PlanAssumption] = Field(default_factory=list)
    events: list[RecoveryEvent] = Field(default_factory=list)
    pending_approval: ApprovalRequest | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def updated_at_must_not_precede_created_at(self) -> "RecoveryCase":
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot be before created_at")
        return self
