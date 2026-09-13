"""Recovery-level reasoning that scopes work for the Constraint Planner."""

import json
from enum import StrEnum
from typing import Any, Protocol

from pydantic import Field
from strands import Agent
from strands.models import BedrockModel

from app.agent.config import RecoveryAgentConfig
from app.agent.recovery_agent import ToolInvocationRecorder, model_call_count
from app.fixtures import DemoScenario
from app.models import (
    ContractModel,
    CoverageWindow,
    RecoveryEvent,
    RecoveryPlanSegment,
    RecoveryStatus,
)
from app.services import InvalidationOutcome, RecoveryNeed, SegmentImpactReason
from app.tools import get_childcare_schedule, use_scenario


class PlanningMode(StrEnum):
    """Recovery situations that require materially different planning direction."""

    INITIAL = "initial"
    WORLD_STATE_REPLAN = "world_state_replan"


class ConstraintCategory(StrEnum):
    """Authoritative context categories the Planner may need to resolve a brief."""

    COVERAGE = "coverage"
    PARENT_CALENDARS = "parent_calendars"
    CAREGIVER_AVAILABILITY = "caregiver_availability"
    FAMILY_PREFERENCES = "family_preferences"
    FAMILY_POLICY = "family_policy"
    PLAN_PRESERVATION = "plan_preservation"


class PlanningBrief(ContractModel):
    """Transient, structured Orchestrator-to-Planner contract; never persisted."""

    recovery_case_id: str | None = None
    planning_mode: PlanningMode
    planning_required: bool
    objective: str = Field(min_length=1, max_length=500)
    triggering_event: RecoveryEvent | None = None
    current_active_plan_id: str | None = None
    current_recovery_status: RecoveryStatus | None = None
    invalidated_assumption_ids: list[str] = Field(default_factory=list)
    required_coverage_window: CoverageWindow
    affected_windows: list[CoverageWindow] = Field(default_factory=list)
    affected_segments: list[RecoveryPlanSegment] = Field(default_factory=list)
    affected_segment_reasons: list[SegmentImpactReason] = Field(default_factory=list)
    preserved_segments: list[RecoveryPlanSegment] = Field(default_factory=list)
    excluded_caregiver_ids: list[str] = Field(default_factory=list)
    relevant_constraint_categories: list[ConstraintCategory] = Field(min_length=1)
    planner_directives: list[str] = Field(default_factory=list, max_length=8)
    known_options_insufficient: bool = False
    unresolved_known_option_windows: list[CoverageWindow] = Field(default_factory=list)
    backup_research_needed: bool = False
    researched_candidate_ids: list[str] = Field(default_factory=list)
    recommended_backup_care_candidate_id: str | None = None


class RecoveryOrchestratorLike(Protocol):
    """Narrow structured invocation surface for real Strands and offline fakes."""

    def __call__(
        self,
        prompt: str,
        *,
        structured_output_model: type[PlanningBrief] | None = None,
    ) -> Any: ...


class OrchestratorResult(ContractModel):
    """Observable result of one recovery-level orchestration decision."""

    brief: PlanningBrief
    model_call_count: int = Field(default=0, ge=0)
    tools_used: list[str] = Field(default_factory=list)


ORCHESTRATOR_INSTRUCTIONS = """
You are DayMend's Recovery Orchestrator. You reason about the recovery objective and the scope of
planning work after a childcare disruption or a recorded world-state change. Produce a concise
PlanningBrief for a separate Constraint Planner.

Use get_childcare_schedule to confirm the authoritative required coverage window. Application
code supplies deterministic impact facts for replanning: affected windows, preserved segments,
and excluded caregivers. Treat those facts as authoritative: preserved segments are hard repair
constraints, while affected segments and their connected handoffs are the editable scope. Decide
the planning focus, identify which constraint categories matter, and give concise directives.

When application-supplied interval analysis explicitly reports known_options_insufficient=true
and provides unresolved_known_option_windows, set backup_research_needed=true so the application
can invoke the Backup Care Research Agent. Never request research when the authoritative signal
says known options are sufficient. Do not choose or invent provider candidates yourself.

You do not construct a RecoveryPlan, calculate final cost, validate feasibility, authorize
spending, mutate world state, persist data, execute actions, or mark a case RESOLVED. Do not expose
private reasoning or chain-of-thought. Return only the structured PlanningBrief. Set
planning_required=true when the supplied disruption or uncovered windows require a new plan.
""".strip()


def build_recovery_orchestrator(
    config: RecoveryAgentConfig,
    recorder: ToolInvocationRecorder,
) -> Agent:
    """Create the real Strands Recovery Orchestrator with deliberately narrow tool access."""

    model = BedrockModel(
        model_id=config.model_id,
        region_name=config.region_name,
        temperature=0.0,
        max_tokens=2048,
    )
    return Agent(
        name="daymend_recovery_orchestrator",
        description="Scopes childcare recovery and replanning work for a constraint planner.",
        model=model,
        tools=[get_childcare_schedule],
        system_prompt=ORCHESTRATOR_INSTRUCTIONS,
        callback_handler=recorder,
    )


def create_initial_planning_brief(
    *,
    orchestrator: RecoveryOrchestratorLike,
    recorder: ToolInvocationRecorder,
    disruption: str,
    scenario: DemoScenario,
    recovery_need: RecoveryNeed | None = None,
) -> OrchestratorResult:
    """Ask the Orchestrator to scope a new childcare-recovery objective."""

    context = {
        "planning_mode": PlanningMode.INITIAL,
        "disruption": disruption,
        "authoritative_required_coverage": scenario.required_coverage.model_dump(mode="json"),
        "known_option_recovery_need": (
            recovery_need.model_dump(mode="json") if recovery_need is not None else None
        ),
    }
    return _invoke_orchestrator(
        orchestrator=orchestrator,
        recorder=recorder,
        scenario=scenario,
        prompt=(
            "Create the planning brief for this newly detected childcare disruption. Identify the "
            "recovery objective and the authoritative context categories the Constraint Planner "
            f"must consult. Recovery context: {_compact_json(context)}"
        ),
        authoritative_updates={
            "recovery_case_id": None,
            "planning_mode": PlanningMode.INITIAL,
            "triggering_event": None,
            "current_active_plan_id": None,
            "current_recovery_status": None,
            "invalidated_assumption_ids": [],
            "required_coverage_window": scenario.required_coverage,
            "affected_windows": [scenario.required_coverage],
            "affected_segments": [],
            "affected_segment_reasons": [],
            "preserved_segments": [],
            "excluded_caregiver_ids": [],
            "known_options_insufficient": (
                recovery_need.known_options_insufficient if recovery_need is not None else False
            ),
            "unresolved_known_option_windows": (
                recovery_need.requested_windows if recovery_need is not None else []
            ),
            "researched_candidate_ids": [],
            "recommended_backup_care_candidate_id": None,
        },
        recovery_need=recovery_need,
    )


def create_replanning_brief(
    *,
    orchestrator: RecoveryOrchestratorLike,
    recorder: ToolInvocationRecorder,
    outcome: InvalidationOutcome,
) -> OrchestratorResult:
    """Scope Plan B using deterministic invalidation and impact facts."""

    event = outcome.recovery_case.events[-1]
    context = {
        "planning_mode": PlanningMode.WORLD_STATE_REPLAN,
        "recovery_case_id": outcome.recovery_case.case_id,
        "disruption": outcome.recovery_case.disruption,
        "current_recovery_status": outcome.recovery_case.status,
        "current_active_plan": outcome.recovery_case.active_recovery_plan.model_dump(mode="json"),
        "triggering_event": event.model_dump(mode="json"),
        "invalidated_assumptions": [
            assumption.model_dump(mode="json") for assumption in outcome.invalidated_assumptions
        ],
        "affected_windows": [
            window.model_dump(mode="json") for window in outcome.uncovered_windows
        ],
        "impacted_segments": [
            segment.model_dump(mode="json") for segment in outcome.impacted_segments
        ],
        "impact_reasons": [reason.model_dump(mode="json") for reason in outcome.impact_reasons],
        "preserved_segments": [
            segment.model_dump(mode="json") for segment in outcome.preserved_segments
        ],
    }
    return _invoke_orchestrator(
        orchestrator=orchestrator,
        recorder=recorder,
        scenario=outcome.updated_scenario,
        prompt=(
            "Create the replanning brief after this authoritative world-state change. Decide the "
            "repair focus while retaining every deterministically preserved Plan A segment. "
            f"Deterministic recovery context: {_compact_json(context)}"
        ),
        authoritative_updates={
            "recovery_case_id": outcome.recovery_case.case_id,
            "planning_mode": PlanningMode.WORLD_STATE_REPLAN,
            "triggering_event": event,
            "current_active_plan_id": outcome.recovery_case.active_recovery_plan.plan_id,
            "current_recovery_status": outcome.recovery_case.status,
            "invalidated_assumption_ids": [
                assumption.assumption_id for assumption in outcome.invalidated_assumptions
            ],
            "required_coverage_window": outcome.updated_scenario.required_coverage,
            "affected_windows": list(outcome.uncovered_windows),
            "affected_segments": list(outcome.impacted_segments),
            "affected_segment_reasons": list(outcome.impact_reasons),
            "preserved_segments": list(outcome.preserved_segments),
            "excluded_caregiver_ids": [event.caregiver_id] if event.caregiver_id else [],
            "known_options_insufficient": False,
            "unresolved_known_option_windows": [],
            "backup_research_needed": False,
            "researched_candidate_ids": [],
            "recommended_backup_care_candidate_id": None,
        },
    )


def _invoke_orchestrator(
    *,
    orchestrator: RecoveryOrchestratorLike,
    recorder: ToolInvocationRecorder,
    scenario: DemoScenario,
    prompt: str,
    authoritative_updates: dict[str, Any],
    recovery_need: RecoveryNeed | None = None,
) -> OrchestratorResult:
    tools_before = len(recorder.tool_names)
    with use_scenario(scenario):
        result = orchestrator(prompt, structured_output_model=PlanningBrief)
    if result.structured_output is None:
        raise RuntimeError("Strands Recovery Orchestrator returned no PlanningBrief")
    brief = result.structured_output.model_copy(update=authoritative_updates)
    if not brief.planning_required:
        raise RuntimeError("Recovery Orchestrator declined required childcare planning")
    if recovery_need is not None:
        if recovery_need.research_needed and not brief.backup_research_needed:
            raise RuntimeError(
                "Recovery Orchestrator did not request research for an unresolved known-options gap"
            )
        if not recovery_need.research_needed:
            brief = brief.model_copy(update={"backup_research_needed": False})
    return OrchestratorResult(
        brief=brief,
        model_call_count=model_call_count(result),
        tools_used=recorder.tool_names[tools_before:],
    )


def _compact_json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), default=str)
