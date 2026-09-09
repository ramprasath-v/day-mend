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


class RecoveryEventType(StrEnum):
    """External or internal facts currently represented in recovery history."""

    DISRUPTION_DETECTED = "DISRUPTION_DETECTED"
    CAREGIVER_DECLINED = "CAREGIVER_DECLINED"
    APPROVAL_REQUESTED = "APPROVAL_REQUESTED"
    APPROVAL_APPROVED = "APPROVAL_APPROVED"
    APPROVAL_REJECTED = "APPROVAL_REJECTED"
    EXECUTION_STARTED = "EXECUTION_STARTED"
    ACTION_COMPLETED = "ACTION_COMPLETED"
    ACTION_FAILED = "ACTION_FAILED"
    COMPLETION_VERIFIED = "COMPLETION_VERIFIED"
    CASE_RESOLVED = "CASE_RESOLVED"


class PlanAssumptionStatus(StrEnum):
    """Whether an assumption may still support an active plan."""

    ACTIVE = "ACTIVE"
    INVALIDATED = "INVALIDATED"


class PlanValidationState(StrEnum):
    """Result of deterministic plan validation."""

    NOT_VALIDATED = "NOT_VALIDATED"
    VALID = "VALID"
    INVALID = "INVALID"


class ApprovalStatus(StrEnum):
    """Decision state for an autonomy-boundary request."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ApprovalType(StrEnum):
    """Consequential action categories that may cross an autonomy boundary."""

    SPEND_ABOVE_AUTONOMY_LIMIT = "SPEND_ABOVE_AUTONOMY_LIMIT"
    UNFAMILIAR_PAID_CAREGIVER = "UNFAMILIAR_PAID_CAREGIVER"


class PlanApprovalReason(StrEnum):
    """Deterministic reasons a valid plan still requires human permission."""

    COST_ABOVE_AUTOMATIC_LIMIT = "COST_ABOVE_AUTOMATIC_LIMIT"
    UNFAMILIAR_PAID_CAREGIVER = "UNFAMILIAR_PAID_CAREGIVER"


class BackupCareProviderType(StrEnum):
    """Synthetic provider categories available to backup-care research."""

    INDEPENDENT_CAREGIVER = "INDEPENDENT_CAREGIVER"
    LOCAL_AGENCY = "LOCAL_AGENCY"
    EMPLOYER_NETWORK = "EMPLOYER_NETWORK"


class ExecutionActionType(StrEnum):
    """Small set of simulated recovery operations used before real integrations exist."""

    RESERVE_CAREGIVER = "RESERVE_CAREGIVER"
    UPDATE_CALENDAR = "UPDATE_CALENDAR"


class ExecutionActionStatus(StrEnum):
    """Deterministic execution outcome for one planned operation."""

    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


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
    critical: bool = False


class CareLocationType(StrEnum):
    """Small, synthetic location taxonomy used by deterministic movement checks."""

    FAMILY_HOME = "FAMILY_HOME"
    CAREGIVER_HOME = "CAREGIVER_HOME"
    OTHER = "OTHER"


class Caregiver(ContractModel):
    """A potential caregiver and the known facts relevant to recovery."""

    caregiver_id: str
    name: str
    is_trusted: bool
    relationship: str | None = None
    availability: list[CoverageWindow] = Field(default_factory=list)
    hourly_rate: Decimal | None = Field(default=None, ge=0)
    flat_rate: Decimal | None = Field(default=None, ge=0)
    handoff_buffer_minutes: int = Field(default=0, ge=0)
    known_to_family: bool = True
    previously_used: bool = False
    external_provider: bool = False
    care_location_type: CareLocationType = CareLocationType.FAMILY_HOME
    location_id: str = "family_home"
    location_label: str = "Family home"
    travel_minutes_from_family_home: int = Field(default=0, ge=0)
    can_transport_child: bool = False

    @model_validator(mode="after")
    def has_at_most_one_price_type(self) -> "Caregiver":
        if self.hourly_rate is not None and self.flat_rate is not None:
            raise ValueError("caregiver cannot have both hourly_rate and flat_rate")
        return self


class FamilyPreferences(ContractModel):
    """Soft priorities that help the agent rank otherwise valid plans."""

    prefer_family_first: bool = False
    prefer_fewer_handoffs: bool = False
    prefer_parent_a_morning_coverage: bool = False
    avoid_rescheduling_customer_meetings: bool = False
    preferred_backup_order: list[str] = Field(default_factory=list)
    preferred_handoff_location: str | None = None
    prefer_closer_backup_care: bool = False
    prefer_lower_backup_care_cost: bool = False
    preferred_minimum_provider_rating: Decimal | None = Field(default=None, ge=0, le=5)
    prefer_meaningful_review_history: bool = False
    prefer_previously_used_provider: bool = False


class FamilyPolicy(ContractModel):
    """Hard rules and autonomy boundaries enforced deterministically."""

    require_trusted_caregiver: bool = True
    unapproved_caregiver_allowed: bool = False
    automatic_spend_limit: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        description=(
            "Autonomy threshold above which a feasible plan requires approval; not a budget "
            "or feasibility limit."
        ),
    )
    currency: str = Field(default="USD", min_length=3, max_length=3)
    minimum_handoff_minutes: int = Field(default=0, ge=0)
    require_verified_backup_provider: bool = False
    require_background_checked_backup_provider: bool = False
    require_approval_for_unfamiliar_paid_caregiver: bool = False


class CoverageSource(StrEnum):
    """Kind of person assigned to a coverage segment."""

    CAREGIVER = "CAREGIVER"
    PARENT = "PARENT"


class PlanSegmentType(StrEnum):
    """Whether a supervised interval is stationary care or child transport."""

    CARE = "CARE"
    TRANSPORT = "TRANSPORT"


class ParentTransportCapability(ContractModel):
    """Authoritative parent driving capability and bounded transport availability."""

    parent_id: str
    can_transport_child: bool = False
    availability: list[CoverageWindow] = Field(default_factory=list)


class RecoveryPlanSegment(ContractModel):
    """One continuous portion of childcare coverage in a proposed plan."""

    segment_id: str
    window: CoverageWindow
    assigned_person_id: str
    source: CoverageSource
    segment_type: PlanSegmentType = PlanSegmentType.CARE
    location_id: str = "family_home"
    location_label: str = "Family home"
    destination_location_id: str | None = None
    destination_location_label: str | None = None
    transporter_id: str | None = None
    estimated_cost: Decimal = Field(default=Decimal("0"), ge=0)

    @model_validator(mode="after")
    def transport_has_destination_and_driver(self) -> "RecoveryPlanSegment":
        if self.segment_type is PlanSegmentType.TRANSPORT and (
            self.destination_location_id is None or self.transporter_id is None
        ):
            raise ValueError(
                "transport segments require destination_location_id and transporter_id"
            )
        return self


class BackupCareCandidate(ContractModel):
    """One synthetic provider record available to grounded backup-care research."""

    candidate_id: str
    display_name: str
    provider_type: BackupCareProviderType
    availability: list[CoverageWindow] = Field(default_factory=list)
    hourly_rate: Decimal | None = Field(default=None, ge=0)
    flat_rate: Decimal | None = Field(default=None, ge=0)
    distance_miles: Decimal = Field(ge=0)
    rating: Decimal = Field(ge=0, le=5)
    review_count: int = Field(ge=0)
    verified: bool
    background_checked: bool
    minimum_child_age: int = Field(ge=0)
    maximum_child_age: int = Field(ge=0)
    known_to_family: bool = False
    previously_used: bool = False
    source: str
    care_location_type: CareLocationType = CareLocationType.FAMILY_HOME
    location_id: str = "family_home"
    location_label: str = "Family home"
    travel_minutes_from_family_home: int = Field(default=0, ge=0)
    can_transport_child: bool = False

    @model_validator(mode="after")
    def candidate_contract_is_consistent(self) -> "BackupCareCandidate":
        if self.hourly_rate is not None and self.flat_rate is not None:
            raise ValueError("backup-care candidate cannot have both hourly and flat pricing")
        if self.hourly_rate is None and self.flat_rate is None:
            raise ValueError("backup-care candidate requires hourly or flat pricing")
        if self.maximum_child_age < self.minimum_child_age:
            raise ValueError("maximum_child_age must be at least minimum_child_age")
        return self


class PlanAssumption(ContractModel):
    """A world-state fact on which coverage depends, not a policy-evaluation result."""

    assumption_id: str
    assumption_type: str = Field(
        description=(
            "World-state fact type; cost thresholds and approval requirements are not assumptions."
        )
    )
    subject_id: str
    relevant_window: CoverageWindow | None = None
    value: Any | None = None
    status: PlanAssumptionStatus = PlanAssumptionStatus.ACTIVE
    invalidated_at: AwareDatetime | None = None
    invalidation_reason: str | None = None
    triggering_event_id: str | None = None

    @model_validator(mode="after")
    def invalidation_details_match_status(self) -> "PlanAssumption":
        if self.status is PlanAssumptionStatus.ACTIVE and (
            self.invalidated_at is not None
            or self.invalidation_reason is not None
            or self.triggering_event_id is not None
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
    validation_state: PlanValidationState = PlanValidationState.NOT_VALIDATED
    validation_errors: list[str] = Field(default_factory=list)
    approval_reasons: list[PlanApprovalReason] = Field(default_factory=list)


class ApprovalRequest(ContractModel):
    """A meaningful decision that must be made by the parent."""

    approval_id: str
    recovery_case_id: str
    approval_type: ApprovalType
    plan_id: str
    reason: str
    summary: str
    consequence: str
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


class ExecutionAction(ContractModel):
    """One explicit simulated side effect and its auditable result."""

    action_id: str
    action_type: ExecutionActionType
    target_id: str
    plan_id: str
    status: ExecutionActionStatus = ExecutionActionStatus.PENDING
    attempted_at: AwareDatetime
    completed_at: AwareDatetime | None = None
    result: str | None = None
    error: str | None = None

    @model_validator(mode="after")
    def completion_fields_match_status(self) -> "ExecutionAction":
        if self.status is ExecutionActionStatus.PENDING and self.completed_at is not None:
            raise ValueError("pending execution actions cannot have completed_at")
        if self.status is not ExecutionActionStatus.PENDING and self.completed_at is None:
            raise ValueError("completed execution actions require completed_at")
        if self.status is ExecutionActionStatus.FAILED and not self.error:
            raise ValueError("failed execution actions require an error")
        return self


class RecoveryEvent(ContractModel):
    """An immutable-style fact recorded in a recovery case history."""

    event_id: str
    event_type: RecoveryEventType
    occurred_at: AwareDatetime
    caregiver_id: str | None = None
    relevant_window: CoverageWindow | None = None
    message: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def caregiver_decline_has_response_details(self) -> "RecoveryEvent":
        if self.event_type is RecoveryEventType.CAREGIVER_DECLINED and (
            not self.caregiver_id or not self.message or self.relevant_window is None
        ):
            raise ValueError(
                "caregiver decline events require caregiver_id, message, and relevant_window"
            )
        return self


class RecoveryCase(ContractModel):
    """Persistent aggregate for a childcare disruption and its recovery history."""

    case_id: str
    status: RecoveryStatus = RecoveryStatus.DETECTED
    disruption: str
    coverage_gap: CoverageWindow
    uncovered_windows: list[CoverageWindow] = Field(default_factory=list)
    context_state: dict[str, Any] = Field(default_factory=dict)
    family_policy: FamilyPolicy | None = None
    active_recovery_plan: RecoveryPlan | None = None
    previous_plans: list[RecoveryPlan] = Field(default_factory=list)
    assumptions: list[PlanAssumption] = Field(default_factory=list)
    events: list[RecoveryEvent] = Field(default_factory=list)
    pending_approval: ApprovalRequest | None = None
    approval_history: list[ApprovalRequest] = Field(default_factory=list)
    execution_history: list[ExecutionAction] = Field(default_factory=list)
    latest_replan_trigger_event_id: str | None = None
    completion_verified_at: AwareDatetime | None = None
    version: int = Field(default=0, ge=0)
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def updated_at_must_not_precede_created_at(self) -> "RecoveryCase":
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot be before created_at")
        return self
