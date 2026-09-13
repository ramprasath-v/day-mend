"""Constraint-focused plan construction and validator-driven draft repair."""

import hashlib
import json
from datetime import timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Protocol

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
    CoverageSource,
    CoverageWindow,
    PlanValidationState,
    RecoveryPlan,
    RecoveryPlanSegment,
)
from app.observability import log_event
from app.services import PlanValidationIssue, PlanValidator
from app.tools import RECOVERY_CONTEXT_TOOLS, use_scenario
from app.tools.recovery_context import planner_context_snapshot

CONSTRAINT_PLANNER_INSTRUCTIONS = (
    RECOVERY_AGENT_INSTRUCTIONS.replace(
        "You are the single DayMend Recovery Agent. Your job is to propose practical childcare "
        "recovery\nplans for an initial disruption and, when application code explicitly "
        "supplies a "
        "recorded\nexternal event and updated world state, to produce a replacement plan.",
        "You are DayMend's Constraint Planner Agent. Your job is to construct practical childcare "
        "RecoveryPlan proposals from a structured PlanningBrief and authoritative context tools.",
    )
    .replace(
        "You receive only the disruption.",
        "You receive a structured PlanningBrief from the Recovery Orchestrator.",
    )
    .replace(
        "This childcare recovery decision requires all five context categories. Before proposing a "
        "plan,\ncall each of these tools at least once: get_childcare_schedule, "
        "get_parent_calendars,\nget_caregivers, get_family_preferences, and get_family_policy. Do "
        "not infer or skip policy and\npreference data merely because caregiver availability "
        "appears "
        "sufficient.",
        "For INITIAL_PLANNING, application code has already normalized all five authoritative "
        "context categories into FeasibleAssignmentMatrix and SoftRankingPreferences. Compose only "
        "from those normalized primitives; do not call the context tools or re-derive eligibility. "
        "Repair and replanning inputs explicitly provide their complete authoritative context.",
    )
)
CONSTRAINT_PLANNER_INSTRUCTIONS = (
    CONSTRAINT_PLANNER_INSTRUCTIONS.replace(
        "You receive a structured PlanningBrief from the Recovery Orchestrator. Decide which "
        "available read-only tools you need and call them\nto learn the required coverage window, "
        "parent calendars, caregiver facts, soft family\npreferences, and hard family policy. Do "
        "not invent a caregiver, parent, calendar event,\navailability window, price, or policy "
        "that the tools did not return.",
        "You receive a complete structured PlannerInvocationInput. For INITIAL_PLANNING, its "
        "FeasibleAssignmentMatrix is the only feasibility source and all windows use start/end. "
        "SoftRankingPreferences are separate and rank feasible combinations only. For repair and "
        "replanning, authoritative_context supplies the unchanged raw tool facts. Do not invent a "
        "person, event, availability window, route, price, or policy.",
    )
    .replace(
        "Establish the exact coverage_required_from and coverage_required_to timestamps.",
        "Establish the exact required coverage window start and end timestamps.",
    )
    .replace(
        "Enumerate parent and caregiver coverage candidates from tool facts.",
        "Enumerate parent and caregiver candidates from permitted matrix primitives or the "
        "supplied authoritative context.",
    )
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


class MovableCalendarConstraint(ContractModel):
    """A movable event requiring a calendar change if parent care overlaps it."""

    event_id: str
    window: CoverageWindow


class FeasiblePersonAssignment(ContractModel):
    """Solution-neutral care primitives for one eligible person."""

    person_id: str
    source: CoverageSource
    permitted_care_windows: list[CoverageWindow]
    allowed_care_location_ids: list[str]
    hard_policy_eligible: bool
    is_trusted: bool | None = None
    hourly_rate: Decimal | None = None
    flat_rate: Decimal | None = None
    handoff_buffer_minutes: int = 0
    movable_calendar_constraints: list[MovableCalendarConstraint] = Field(default_factory=list)


class FeasibleTransportPrimitive(ContractModel):
    """One eligible transporter-window-route combination for Planner selection."""

    transporter_id: str
    permitted_window: CoverageWindow
    origin_location_id: str
    destination_location_id: str
    required_duration_minutes: int
    capability: Literal["ALLOWED"] = "ALLOWED"


class FeasibleAssignmentMatrix(ContractModel):
    """Normalized feasible primitives derived from authoritative initial facts."""

    required_coverage_window: CoverageWindow
    people: list[FeasiblePersonAssignment]
    transport_primitives: list[FeasibleTransportPrimitive]
    family_home_location_id: str
    require_trusted_caregiver: bool
    unapproved_caregiver_allowed: bool
    minimum_handoff_minutes: int
    continuous_supervision_required: bool = True
    explicit_transport_for_location_changes_required: bool = True


class PlannerInvocationInput(ContractModel):
    """Complete, conversation-independent input for one plan proposal or repair."""

    operation: PlannerOperation
    planning_brief: PlanningBrief
    authoritative_context: PlannerAuthoritativeContext | None = None
    feasible_assignment_matrix: FeasibleAssignmentMatrix | None = None
    soft_ranking_preferences: dict[str, Any] | None = None
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
        if self.operation is PlannerOperation.INITIAL_PLANNING and (
            self.authoritative_context is not None
            or self.feasible_assignment_matrix is None
            or self.soft_ranking_preferences is None
        ):
            raise ValueError(
                "INITIAL_PLANNING requires only normalized feasibility and soft preferences"
            )
        if self.operation is not PlannerOperation.INITIAL_PLANNING and (
            self.authoritative_context is None or self.feasible_assignment_matrix is not None
        ):
            raise ValueError("repair and replanning require authoritative context")
        return self


def _window_from_values(start: str, end: str) -> CoverageWindow:
    return CoverageWindow.model_validate({"start": start, "end": end})


def _window_intersection(window: CoverageWindow, required: CoverageWindow) -> CoverageWindow | None:
    start = max(window.start, required.start)
    end = min(window.end, required.end)
    return CoverageWindow(start=start, end=end) if start < end else None


def _subtract_windows(
    window: CoverageWindow, blocked: list[CoverageWindow]
) -> list[CoverageWindow]:
    remaining = [window]
    for block in sorted(blocked, key=lambda item: (item.start, item.end)):
        next_remaining: list[CoverageWindow] = []
        for candidate in remaining:
            if block.end <= candidate.start or block.start >= candidate.end:
                next_remaining.append(candidate)
                continue
            if candidate.start < block.start:
                next_remaining.append(CoverageWindow(start=candidate.start, end=block.start))
            if block.end < candidate.end:
                next_remaining.append(CoverageWindow(start=block.end, end=candidate.end))
        remaining = next_remaining
    return remaining


def _build_feasible_assignment_matrix(
    context: PlannerAuthoritativeContext,
) -> FeasibleAssignmentMatrix:
    """Normalize authoritative facts into eligible solution-neutral primitives."""

    schedule = context.childcare_schedule
    required = _window_from_values(
        schedule["coverage_required_from"], schedule["coverage_required_to"]
    )
    unavailable = set(schedule["unavailable_caregiver_ids"])
    policy = context.family_policy
    caregivers = sorted(context.caregivers["caregivers"], key=lambda item: item["caregiver_id"])
    parents = sorted(context.parent_calendars["parents"], key=lambda item: item["parent_id"])
    eligible_caregivers = [
        caregiver
        for caregiver in caregivers
        if caregiver["caregiver_id"] not in unavailable
        and (not caregiver["external_provider"] or policy["allow_external_backup_providers"])
        and (
            caregiver["is_trusted"]
            or (not policy["require_trusted_caregiver"] and policy["unapproved_caregiver_allowed"])
        )
    ]
    people: list[FeasiblePersonAssignment] = []
    feasible_caregivers: list[dict[str, Any]] = []
    transporter_windows: dict[str, list[CoverageWindow]] = {}
    for caregiver in eligible_caregivers:
        care_windows = [
            intersection
            for raw_window in caregiver["availability_windows"]
            if (
                intersection := _window_intersection(
                    _window_from_values(raw_window["available_from"], raw_window["available_to"]),
                    required,
                )
            )
            is not None
        ]
        if not care_windows:
            continue
        feasible_caregivers.append(caregiver)
        if caregiver["can_transport_child"] and (
            not caregiver["external_provider"] or policy["allow_provider_transport"]
        ):
            transporter_windows[caregiver["caregiver_id"]] = care_windows
        people.append(
            FeasiblePersonAssignment(
                person_id=caregiver["caregiver_id"],
                source=CoverageSource.CAREGIVER,
                permitted_care_windows=care_windows,
                allowed_care_location_ids=[caregiver["location_id"]],
                hard_policy_eligible=True,
                is_trusted=caregiver["is_trusted"],
                hourly_rate=caregiver["hourly_rate"],
                flat_rate=caregiver["flat_rate"],
                handoff_buffer_minutes=caregiver["handoff_buffer_minutes"],
            )
        )

    known_locations = sorted(
        {
            schedule["family_home_location_id"],
            *(caregiver["location_id"] for caregiver in feasible_caregivers),
        }
    )
    for parent in parents:
        events = sorted(parent["events"], key=lambda item: item["event_id"])
        blocked = [
            _window_from_values(event["starts_at"], event["ends_at"])
            for event in events
            if event["critical"] or not event["movable"]
        ]
        care_windows = _subtract_windows(required, blocked)
        transport_windows: list[CoverageWindow] = []
        if parent["transport"]["can_transport_child"]:
            for raw_window in parent["transport"]["availability"]:
                intersection = _window_intersection(
                    CoverageWindow.model_validate(raw_window), required
                )
                if intersection is not None:
                    transport_windows.extend(_subtract_windows(intersection, blocked))
        if transport_windows:
            transporter_windows[parent["parent_id"]] = transport_windows
        people.append(
            FeasiblePersonAssignment(
                person_id=parent["parent_id"],
                source=CoverageSource.PARENT,
                permitted_care_windows=care_windows,
                allowed_care_location_ids=known_locations,
                hard_policy_eligible=True,
                movable_calendar_constraints=[
                    MovableCalendarConstraint(
                        event_id=event["event_id"],
                        window=_window_from_values(event["starts_at"], event["ends_at"]),
                    )
                    for event in events
                    if event["movable"] and not event["critical"]
                ],
            )
        )

    routes: list[tuple[str, str, int]] = []
    home = schedule["family_home_location_id"]
    for caregiver in feasible_caregivers:
        destination = caregiver["location_id"]
        if destination == home:
            continue
        duration = caregiver["travel_minutes_from_family_home"]
        routes.extend([(home, destination, duration), (destination, home, duration)])
    transport_primitives = [
        FeasibleTransportPrimitive(
            transporter_id=transporter_id,
            permitted_window=window,
            origin_location_id=origin,
            destination_location_id=destination,
            required_duration_minutes=duration,
        )
        for transporter_id, windows in sorted(transporter_windows.items())
        for window in sorted(windows, key=lambda item: (item.start, item.end))
        for origin, destination, duration in sorted(routes)
        if window.end - window.start >= timedelta(minutes=duration)
    ]
    return FeasibleAssignmentMatrix(
        required_coverage_window=required,
        people=sorted(people, key=lambda item: (item.source.value, item.person_id)),
        transport_primitives=transport_primitives,
        family_home_location_id=schedule["family_home_location_id"],
        require_trusted_caregiver=policy["require_trusted_caregiver"],
        unapproved_caregiver_allowed=policy["unapproved_caregiver_allowed"],
        minimum_handoff_minutes=policy["minimum_handoff_minutes"],
    )


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
    authoritative_context = PlannerAuthoritativeContext(
        childcare_schedule=context["get_childcare_schedule"],
        parent_calendars=context["get_parent_calendars"],
        caregivers=context["get_caregivers"],
        family_preferences=context["get_family_preferences"],
        family_policy=context["get_family_policy"],
    )
    return PlannerInvocationInput(
        operation=operation,
        planning_brief=brief,
        authoritative_context=(
            None if operation is PlannerOperation.INITIAL_PLANNING else authoritative_context
        ),
        feasible_assignment_matrix=(
            _build_feasible_assignment_matrix(authoritative_context)
            if operation is PlannerOperation.INITIAL_PLANNING
            else None
        ),
        soft_ranking_preferences=(
            authoritative_context.family_preferences
            if operation is PlannerOperation.INITIAL_PLANNING
            else None
        ),
        previous_candidate=previous_candidate,
        validator_feedback=validator_feedback or [],
        affected_windows=brief.affected_windows,
        affected_segments=brief.affected_segments,
        preserved_segments=brief.preserved_segments,
    )


def canonical_planner_input(planner_input: PlannerInvocationInput) -> str:
    """Serialize Planner input deterministically for rendering and safe digesting."""

    payload = planner_input.model_dump(mode="json")
    for optional_field in (
        "authoritative_context",
        "feasible_assignment_matrix",
        "soft_ranking_preferences",
    ):
        if payload[optional_field] is None:
            del payload[optional_field]
    return json.dumps(
        payload,
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

    if planner_input.operation is PlannerOperation.PLAN_REPAIR:
        action = (
            "Repair every listed deterministic-validator issue and return a complete replacement "
            "RecoveryPlan."
        )
    else:
        action = "Return one complete RecoveryPlan for the full required coverage window."
    if planner_input.preserved_segments:
        action += (
            " Every segment in preserved_segments is a hard constraint and must remain materially "
            "unchanged. Change only affected_segments and their connected handoffs."
        )
    if planner_input.operation is PlannerOperation.PLAN_REPAIR:
        action += (
            " Do not introduce new gaps, overlaps, conflicts, unavailable-caregiver assignments, "
            "or infeasible handoffs."
        )
    initial_constraint_direction = (
        " Compose the plan only from FeasibleAssignmentMatrix primitives. Every care or "
        "transport segment must fit wholly inside its selected primitive's permitted_window. "
        "Select transporter_id, origin, and destination only from one listed transport primitive; "
        "do not invent or combine transport fields across primitives. SoftRankingPreferences rank "
        "feasible options only. Do not call context tools or re-derive eligibility for this "
        "initial proposal."
        if planner_input.operation is PlannerOperation.INITIAL_PLANNING
        else ""
    )
    context_description = (
        "the normalized FeasibleAssignmentMatrix and separate SoftRankingPreferences"
        if planner_input.operation is PlannerOperation.INITIAL_PLANNING
        else "the PlanningBrief and the results of all five context tools"
    )
    return (
        f"{action} Treat the complete structured PlannerInvocationInput below as authoritative; "
        f"it contains {context_description}. Do not depend "
        "on prior conversation for correctness. Keep validation_state NOT_VALIDATED."
        f"{initial_constraint_direction} "
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
        validation = (
            deterministic_validator.validate_repair(
                proposal,
                scenario,
                brief.preserved_segments,
            )
            if brief.preserved_segments
            else deterministic_validator.validate(proposal, scenario)
        )
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
        planner_invocation_count=len(attempts)
        + (1 if initial_operation is PlannerOperation.REPLANNING else 0),
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
        if resolved_operation is PlannerOperation.REPLANNING:
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
