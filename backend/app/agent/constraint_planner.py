"""Constraint-focused plan construction and validator-driven draft repair."""

import hashlib
import json
from enum import StrEnum
from typing import Any, Protocol

from pydantic import Field, model_validator
from strands import Agent
from strands.models import BedrockModel

from app.agent.config import RecoveryAgentConfig
from app.agent.instructions import RECOVERY_AGENT_INSTRUCTIONS
from app.agent.recovery_agent import (
    MAX_PLAN_ATTEMPTS,
    InitialPlanningResult,
    PlanningAttempt,
    ToolInvocationRecorder,
    build_planning_result,
    model_call_count,
)
from app.agent.recovery_orchestrator import PlanningBrief, PlanningMode
from app.fixtures import DemoScenario
from app.models import (
    ContractModel,
    CoverageWindow,
    PlanValidationState,
    RecoveryPlan,
    RecoveryPlanSegment,
)
from app.observability import log_event
from app.services import PlanValidationIssue, PlanValidator
from app.tools import RECOVERY_CONTEXT_TOOLS, use_scenario
from app.tools.recovery_context import planner_context_snapshot

CONSTRAINT_PLANNER_INSTRUCTIONS = RECOVERY_AGENT_INSTRUCTIONS.replace(
    "You are the single DayMend Recovery Agent. Your job is to propose practical childcare "
    "recovery\nplans for an initial disruption and, when application code explicitly supplies a "
    "recorded\nexternal event and updated world state, to produce a replacement plan.",
    "You are DayMend's Constraint Planner Agent. Your job is to construct practical childcare "
    "RecoveryPlan proposals from a structured PlanningBrief and authoritative context tools.",
).replace(
    "You receive only the disruption.",
    "You receive a structured PlanningBrief from the Recovery Orchestrator.",
)


class PlannerOperation(StrEnum):
    """Operation represented in every complete Planner invocation input."""

    INITIAL_PLANNING = "INITIAL_PLANNING"
    REPLANNING = "REPLANNING"
    PLAN_REPAIR = "PLAN_REPAIR"


class PlannerAuthoritativeContext(ContractModel):
    """Canonical results of the five read-only Planner tools."""

    childcare_schedule: dict[str, Any]
    parent_calendars: dict[str, Any]
    caregivers: dict[str, Any]
    family_preferences: dict[str, Any]
    family_policy: dict[str, Any]


class PlannerInvocationInput(ContractModel):
    """Complete, conversation-independent input for one plan proposal or repair."""

    operation: PlannerOperation
    planning_brief: PlanningBrief
    authoritative_context: PlannerAuthoritativeContext
    previous_candidate: RecoveryPlan | None = None
    validator_feedback: list[PlanValidationIssue] = Field(default_factory=list)
    affected_windows: list[CoverageWindow] = Field(default_factory=list)
    affected_segments: list[RecoveryPlanSegment] = Field(default_factory=list)
    preserved_segments: list[RecoveryPlanSegment] = Field(default_factory=list)

    @model_validator(mode="after")
    def repair_has_candidate_and_feedback(self) -> "PlannerInvocationInput":
        if self.operation is PlannerOperation.PLAN_REPAIR and (
            self.previous_candidate is None or not self.validator_feedback
        ):
            raise ValueError("PLAN_REPAIR requires previous candidate and validator feedback")
        return self


def build_planner_invocation_input(
    *,
    operation: PlannerOperation,
    brief: PlanningBrief,
    scenario: DemoScenario,
    previous_candidate: RecoveryPlan | None = None,
    validator_feedback: list[PlanValidationIssue] | None = None,
) -> PlannerInvocationInput:
    """Build the shared local/AgentCore Planner contract from authoritative state."""

    context = planner_context_snapshot(scenario)
    return PlannerInvocationInput(
        operation=operation,
        planning_brief=brief,
        authoritative_context=PlannerAuthoritativeContext(
            childcare_schedule=context["get_childcare_schedule"],
            parent_calendars=context["get_parent_calendars"],
            caregivers=context["get_caregivers"],
            family_preferences=context["get_family_preferences"],
            family_policy=context["get_family_policy"],
        ),
        previous_candidate=previous_candidate,
        validator_feedback=validator_feedback or [],
        affected_windows=brief.affected_windows,
        affected_segments=brief.affected_segments,
        preserved_segments=brief.preserved_segments,
    )


def canonical_planner_input(planner_input: PlannerInvocationInput) -> str:
    """Serialize Planner input deterministically for rendering and safe digesting."""

    return json.dumps(
        planner_input.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )


def planner_input_digest(planner_input: PlannerInvocationInput) -> str:
    """Return a safe digest without logging prompt or context contents."""

    return hashlib.sha256(canonical_planner_input(planner_input).encode()).hexdigest()


def _log_planner_input(planner_input: PlannerInvocationInput, *, stage: str) -> None:
    log_event(
        "planner_input_prepared",
        operation=planner_input.operation,
        stage=stage,
        planner_input_digest=planner_input_digest(planner_input),
        has_previous_candidate=planner_input.previous_candidate is not None,
        validator_issue_count=len(planner_input.validator_feedback),
        affected_window_count=len(planner_input.affected_windows),
        affected_segment_count=len(planner_input.affected_segments),
        preserved_segment_count=len(planner_input.preserved_segments),
    )


def render_planner_input(planner_input: PlannerInvocationInput) -> str:
    """Render the same complete proposal/repair instruction for both runtime paths."""

    action = (
        "Repair every listed deterministic-validator issue and return a complete replacement "
        "RecoveryPlan. Preserve already-valid segments where feasible and do not introduce new "
        "gaps, overlaps, conflicts, unavailable-caregiver assignments, or infeasible handoffs."
        if planner_input.operation is PlannerOperation.PLAN_REPAIR
        else "Return one complete RecoveryPlan for the full required coverage window."
    )
    return (
        f"{action} Treat the complete structured PlannerInvocationInput below as authoritative; "
        "it contains the PlanningBrief and the results of all five context tools. Do not depend "
        "on prior conversation for correctness. Keep validation_state NOT_VALIDATED. "
        f"PlannerInvocationInput: {canonical_planner_input(planner_input)}"
    )


class ConstraintPlannerLike(Protocol):
    """Invocation surface shared by the real Planner and narrow offline fakes."""

    def __call__(
        self,
        prompt: str,
        *,
        structured_output_model: type[RecoveryPlan] | None = None,
    ) -> Any: ...


def build_constraint_planner(
    config: RecoveryAgentConfig,
    recorder: ToolInvocationRecorder,
) -> Agent:
    """Create the real Strands Constraint Planner with all five planning context tools."""

    model = BedrockModel(
        model_id=config.model_id,
        region_name=config.region_name,
        temperature=0.0,
        max_tokens=4096,
    )
    return Agent(
        name="daymend_constraint_planner",
        description="Constructs and repairs childcare coverage-plan proposals.",
        model=model,
        tools=RECOVERY_CONTEXT_TOOLS,
        system_prompt=CONSTRAINT_PLANNER_INSTRUCTIONS,
        callback_handler=recorder,
    )


def run_constraint_planning(
    *,
    planner: ConstraintPlannerLike,
    recorder: ToolInvocationRecorder,
    brief: PlanningBrief,
    scenario: DemoScenario,
    model_id: str,
    validator: PlanValidator | None = None,
    max_attempts: int = MAX_PLAN_ATTEMPTS,
) -> InitialPlanningResult:
    """Use the shared complete Planner input for every local proposal and repair."""

    if not 1 <= max_attempts <= MAX_PLAN_ATTEMPTS:
        raise ValueError(f"max_attempts must be between 1 and {MAX_PLAN_ATTEMPTS}")
    deterministic_validator = validator or PlanValidator()
    initial_operation = (
        PlannerOperation.INITIAL_PLANNING
        if brief.planning_mode is PlanningMode.INITIAL
        else PlannerOperation.REPLANNING
    )
    attempts: list[PlanningAttempt] = []
    proposal_model_calls = 0
    previous_candidate = None
    feedback: list[PlanValidationIssue] = []
    for attempt_number in range(1, max_attempts + 1):
        operation = initial_operation if attempt_number == 1 else PlannerOperation.PLAN_REPAIR
        proposal, calls = propose_constraint_plan(
            planner=planner,
            recorder=recorder,
            brief=brief,
            scenario=scenario,
            operation=operation,
            previous_plan=previous_candidate,
            validator_feedback=feedback,
        )
        proposal_model_calls += calls
        validation = deterministic_validator.validate(proposal, scenario)
        attempts.append(
            PlanningAttempt(
                attempt_number=attempt_number,
                proposed_plan=proposal,
                validation=validation,
                model_call_count=calls,
            )
        )
        if validation.valid or attempt_number == max_attempts:
            break
        previous_candidate = proposal
        feedback = validation.issues

    return build_planning_result(
        success=attempts[-1].validation.valid,
        attempts=attempts,
        recorder=recorder,
        model_id=model_id,
        architecture="multi",
        orchestrator_invocation_count=1,
        planner_invocation_count=1 + len(attempts),
        model_call_count=proposal_model_calls,
    )


def propose_constraint_plan(
    *,
    planner: ConstraintPlannerLike,
    recorder: ToolInvocationRecorder,
    brief: PlanningBrief,
    scenario: DemoScenario,
    operation: PlannerOperation | None = None,
    previous_plan: RecoveryPlan | None = None,
    validator_feedback: list[PlanValidationIssue] | None = None,
) -> tuple[RecoveryPlan, int]:
    """Produce one proposal from the shared conversation-independent Planner input."""

    repair_feedback = validator_feedback or []
    resolved_operation = operation or (
        PlannerOperation.PLAN_REPAIR
        if previous_plan is not None
        else (
            PlannerOperation.INITIAL_PLANNING
            if brief.planning_mode is PlanningMode.INITIAL
            else PlannerOperation.REPLANNING
        )
    )
    planner_input = build_planner_invocation_input(
        operation=resolved_operation,
        brief=brief,
        scenario=scenario,
        previous_candidate=previous_plan,
        validator_feedback=repair_feedback,
    )
    digest = planner_input_digest(planner_input)
    context_model_calls = 0
    with use_scenario(scenario):
        if resolved_operation is not PlannerOperation.PLAN_REPAIR:
            _log_planner_input(planner_input, stage="context_verification")
            context_result = planner(
                "Verify the complete structured PlannerInvocationInput by calling all five "
                "context tools once. Do not return structured output or expose private reasoning. "
                f"Planner input digest: {digest}."
            )
            context_model_calls = model_call_count(context_result)
        _log_planner_input(planner_input, stage="proposal")
        result = planner(render_planner_input(planner_input), structured_output_model=RecoveryPlan)
    if result.structured_output is None:
        raise RuntimeError("Strands returned no structured RecoveryPlan")
    proposal = result.structured_output.model_copy(
        update={"validation_state": PlanValidationState.NOT_VALIDATED, "validation_errors": []}
    )
    return proposal, context_model_calls + model_call_count(result)
