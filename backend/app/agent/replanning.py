"""World-state replanning orchestration for the single DayMend Recovery Agent."""

import json
from decimal import Decimal

from pydantic import Field

from app.agent.recovery_agent import (
    MAX_PLAN_ATTEMPTS,
    PlanningAttempt,
    RecoveryAgentLike,
    ToolInvocationRecorder,
    run_bounded_plan_attempts,
)
from app.fixtures import DemoScenario
from app.models import (
    ContractModel,
    CoverageWindow,
    PlanAssumption,
    RecoveryCase,
    RecoveryEvent,
    RecoveryPlan,
    RecoveryPlanSegment,
    RecoveryStatus,
)
from app.services import (
    PlanInvalidationService,
    PlanValidationIssue,
    PlanValidationResult,
    PlanValidator,
    materialize_caregiver_assumptions,
)
from app.tools import use_scenario


class ReplanningResult(ContractModel):
    """Observable result of one external event and its bounded Plan B workflow."""

    success: bool
    triggering_event: RecoveryEvent
    invalidated_assumptions: list[PlanAssumption] = Field(default_factory=list)
    impacted_segments: list[RecoveryPlanSegment] = Field(default_factory=list)
    preserved_segments: list[RecoveryPlanSegment] = Field(default_factory=list)
    uncovered_windows: list[CoverageWindow] = Field(default_factory=list)
    planning_attempts: list[PlanningAttempt] = Field(default_factory=list)
    total_attempts: int = Field(ge=1, le=MAX_PLAN_ATTEMPTS)
    final_plan: RecoveryPlan | None = None
    final_validation: PlanValidationResult
    deterministic_total_cost: Decimal = Field(ge=0)
    requires_approval: bool
    final_errors: list[PlanValidationIssue] = Field(default_factory=list)
    recovery_case: RecoveryCase
    tools_used: list[str] = Field(default_factory=list)
    status_history: list[RecoveryStatus] = Field(default_factory=list)


def process_external_event(
    *,
    recovery_case: RecoveryCase,
    event: RecoveryEvent,
    scenario: DemoScenario,
    agent: RecoveryAgentLike,
    recorder: ToolInvocationRecorder,
    validator: PlanValidator | None = None,
    invalidation_service: PlanInvalidationService | None = None,
    max_attempts: int = MAX_PLAN_ATTEMPTS,
) -> ReplanningResult:
    """Apply a caregiver decline, then generate and validate Plan B from updated facts."""

    service = invalidation_service or PlanInvalidationService()
    outcome = service.apply_caregiver_decline(recovery_case, event, scenario)
    tools_before_replan = len(recorder.tool_names)
    replan_context = _replanning_context(outcome)

    with use_scenario(outcome.updated_scenario):
        agent(
            "A previously valid recovery plan has been affected by a real external event. "
            "This is world-state replanning, not initial-plan repair. Refresh all five "
            "authoritative context tools because the world state changed. Analyze the recorded "
            "event, invalidated assumptions, impacted segments, preserved segments, and uncovered "
            "windows below. Prefer preserving valid work, but change more if required for a fully "
            "feasible plan. Do not return structured output yet and do not expose private "
            f"reasoning. Updated recovery context: {replan_context}"
        )
        attempts = run_bounded_plan_attempts(
            agent=agent,
            scenario=outcome.updated_scenario,
            proposal_prompt=(
                "Using the refreshed authoritative tools and updated recovery context, return a "
                "complete Plan B RecoveryPlan. It must cover the full required window, must not "
                "assign a declined caregiver during an unavailable window, and should preserve "
                "still-valid Plan A segments when feasible. Keep validation_state NOT_VALIDATED."
            ),
            validator=validator,
            max_attempts=max_attempts,
            repair_scope="Plan-B draft",
        )

    final_validation = attempts[-1].validation
    success = final_validation.valid
    updated_case = outcome.recovery_case
    final_plan: RecoveryPlan | None = None
    if success:
        final_plan = materialize_caregiver_assumptions(final_validation.validated_plan)
        existing_assumption_ids = {
            assumption.assumption_id for assumption in updated_case.assumptions
        }
        assumptions = [
            *updated_case.assumptions,
            *[
                assumption
                for assumption in final_plan.assumptions
                if assumption.assumption_id not in existing_assumption_ids
            ],
        ]
        updated_case = updated_case.model_copy(
            update={
                "status": RecoveryStatus.EXECUTING,
                "active_recovery_plan": final_plan,
                "assumptions": assumptions,
                "uncovered_windows": [],
            }
        )

    return ReplanningResult(
        success=success,
        triggering_event=event,
        invalidated_assumptions=list(outcome.invalidated_assumptions),
        impacted_segments=list(outcome.impacted_segments),
        preserved_segments=list(outcome.preserved_segments),
        uncovered_windows=list(outcome.uncovered_windows),
        planning_attempts=attempts,
        total_attempts=len(attempts),
        final_plan=final_plan,
        final_validation=final_validation,
        deterministic_total_cost=final_validation.deterministic_total_cost,
        requires_approval=final_validation.requires_approval,
        final_errors=[] if success else final_validation.issues,
        recovery_case=updated_case,
        tools_used=recorder.tool_names[tools_before_replan:],
        status_history=[
            recovery_case.status,
            RecoveryStatus.REPLANNING,
            updated_case.status,
        ],
    )


def _replanning_context(outcome) -> str:
    scenario = outcome.updated_scenario
    payload = {
        "original_disruption": outcome.recovery_case.disruption,
        "active_plan_after_invalidation": outcome.recovery_case.active_recovery_plan.model_dump(
            mode="json"
        ),
        "triggering_event": outcome.recovery_case.events[-1].model_dump(mode="json"),
        "invalidated_assumptions": [
            assumption.model_dump(mode="json") for assumption in outcome.invalidated_assumptions
        ],
        "impacted_segments": [
            segment.model_dump(mode="json") for segment in outcome.impacted_segments
        ],
        "preserved_segments": [
            segment.model_dump(mode="json") for segment in outcome.preserved_segments
        ],
        "uncovered_windows": [
            window.model_dump(mode="json") for window in outcome.uncovered_windows
        ],
        "updated_caregiver_availability": {
            caregiver.caregiver_id: [
                window.model_dump(mode="json") for window in caregiver.availability
            ]
            for caregiver in scenario.caregivers
        },
    }
    return json.dumps(payload, separators=(",", ":"))
