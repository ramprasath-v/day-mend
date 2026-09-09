"""Versioned, transport-safe contracts for the stateless DayMend reasoning runtime."""

from enum import StrEnum

from pydantic import Field, model_validator

from app.agent.backup_care_researcher import BackupCareResearchResult
from app.agent.recovery_orchestrator import PlanningBrief
from app.fixtures import DemoScenario
from app.models import (
    BackupCareCandidate,
    CalendarEvent,
    Caregiver,
    ContractModel,
    CoverageWindow,
    FamilyPolicy,
    FamilyPreferences,
    ParentTransportCapability,
    PlanAssumption,
    RecoveryCase,
    RecoveryPlan,
    RecoveryPlanSegment,
    RecoveryStatus,
)
from app.services import PlanValidationIssue

RUNTIME_SCHEMA_VERSION = "1.0"


class RuntimeOperation(StrEnum):
    INITIAL_PLANNING = "INITIAL_PLANNING"
    REPLANNING = "REPLANNING"
    PLAN_REPAIR = "PLAN_REPAIR"


class ScenarioContract(ContractModel):
    disruption: str
    normal_caregiver_id: str
    required_coverage: CoverageWindow
    unavailable_caregiver_ids: list[str]
    parent_ids: list[str]
    parent_events: list[CalendarEvent]
    caregivers: list[Caregiver]
    preferences: FamilyPreferences
    policy: FamilyPolicy
    family_home_location_id: str = "family_home"
    parent_transport_capabilities: list[ParentTransportCapability] = Field(default_factory=list)
    child_age_years: int = 4
    backup_care_candidates: list[BackupCareCandidate] = Field(default_factory=list)

    @classmethod
    def from_scenario(cls, scenario: DemoScenario) -> "ScenarioContract":
        return cls(
            disruption=scenario.disruption,
            normal_caregiver_id=scenario.normal_caregiver_id,
            required_coverage=scenario.required_coverage,
            unavailable_caregiver_ids=list(scenario.unavailable_caregiver_ids),
            parent_ids=list(scenario.parent_ids),
            parent_events=list(scenario.parent_events),
            caregivers=list(scenario.caregivers),
            preferences=scenario.preferences,
            policy=scenario.policy,
            family_home_location_id=scenario.family_home_location_id,
            parent_transport_capabilities=list(scenario.parent_transport_capabilities),
            child_age_years=scenario.child_age_years,
            backup_care_candidates=list(scenario.backup_care_candidates),
        )

    def to_scenario(self) -> DemoScenario:
        return DemoScenario(
            disruption=self.disruption,
            normal_caregiver_id=self.normal_caregiver_id,
            required_coverage=self.required_coverage,
            unavailable_caregiver_ids=tuple(self.unavailable_caregiver_ids),
            parent_ids=tuple(self.parent_ids),
            parent_events=tuple(self.parent_events),
            caregivers=tuple(self.caregivers),
            preferences=self.preferences,
            policy=self.policy,
            family_home_location_id=self.family_home_location_id,
            parent_transport_capabilities=tuple(self.parent_transport_capabilities),
            child_age_years=self.child_age_years,
            backup_care_candidates=tuple(self.backup_care_candidates),
        )


class ReplanningContext(ContractModel):
    recovery_case: RecoveryCase
    previous_status: RecoveryStatus
    original_valid_plan: RecoveryPlan
    invalidated_assumptions: list[PlanAssumption]
    impacted_segments: list[RecoveryPlanSegment]
    preserved_segments: list[RecoveryPlanSegment]
    uncovered_windows: list[CoverageWindow]


class AgentRuntimeRequest(ContractModel):
    schema_version: str = RUNTIME_SCHEMA_VERSION
    request_id: str = Field(min_length=16, max_length=128)
    recovery_case_id: str | None = None
    operation: RuntimeOperation
    architecture: str
    disruption: str | None = None
    scenario: ScenarioContract
    replanning_context: ReplanningContext | None = None
    planning_brief: PlanningBrief | None = None
    previous_plan: RecoveryPlan | None = None
    validator_feedback: list[PlanValidationIssue] = Field(default_factory=list)
    researched_candidate: BackupCareCandidate | None = None

    @model_validator(mode="after")
    def validate_contract(self) -> "AgentRuntimeRequest":
        if self.schema_version != RUNTIME_SCHEMA_VERSION:
            raise ValueError("unsupported AgentCore schema_version")
        if self.architecture not in {"multi", "multi_research"}:
            raise ValueError("AgentCore requires multi or multi_research architecture")
        if self.operation is RuntimeOperation.INITIAL_PLANNING and not self.disruption:
            raise ValueError("INITIAL_PLANNING requires disruption")
        if self.operation is RuntimeOperation.REPLANNING and self.replanning_context is None:
            raise ValueError("REPLANNING requires deterministic replanning_context")
        if self.operation is RuntimeOperation.PLAN_REPAIR and (
            self.planning_brief is None or self.previous_plan is None or not self.validator_feedback
        ):
            raise ValueError("PLAN_REPAIR requires brief, previous plan, and validator feedback")
        return self


class RuntimeMetrics(ContractModel):
    duration_ms: int = Field(ge=0)
    orchestrator_invocation_count: int = Field(default=0, ge=0)
    research_agent_invocation_count: int = Field(default=0, ge=0)
    planner_invocation_count: int = Field(default=0, ge=0)
    model_call_count: int = Field(default=0, ge=0)
    tools_used: list[str] = Field(default_factory=list)


class AgentRuntimeResponse(ContractModel):
    schema_version: str = RUNTIME_SCHEMA_VERSION
    request_id: str
    recovery_case_id: str | None = None
    operation: RuntimeOperation
    success: bool
    planning_brief: PlanningBrief
    plan_candidate: RecoveryPlan
    backup_care_research: BackupCareResearchResult | None = None
    researched_candidate: BackupCareCandidate | None = None
    metrics: RuntimeMetrics

    @model_validator(mode="after")
    def validate_version(self) -> "AgentRuntimeResponse":
        if self.schema_version != RUNTIME_SCHEMA_VERSION:
            raise ValueError("unsupported AgentCore schema_version")
        return self
