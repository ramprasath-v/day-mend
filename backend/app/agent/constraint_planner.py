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
    PlanSegmentType,
    PlanValidationState,
    RecoveryPlan,
    RecoveryPlanSegment,
)
from app.observability import log_event
from app.services import PlanValidationIssue, PlanValidator, ValidationErrorCode
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
        "Repair and replanning inputs provide the same normalized feasibility contract.",
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
        "The same matrix is supplied again for repair and replanning. SoftRankingPreferences are "
        "separate and rank feasible combinations only. Do not invent a "
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


class FeasibleCarePrimitive(ContractModel):
    """One exact stationary-care segment available for Planner composition."""

    primitive_id: str
    assigned_person_id: str
    source: CoverageSource
    segment_type: Literal["CARE"] = "CARE"
    window: CoverageWindow
    location_id: str
    location_label: str
    capability: Literal["ALLOWED"] = "ALLOWED"


class FeasibleTransportPrimitive(ContractModel):
    """One exact supervised-transport segment available for Planner composition."""

    primitive_id: str
    assigned_person_id: str
    source: CoverageSource
    segment_type: Literal["TRANSPORT"] = "TRANSPORT"
    transporter_id: str
    window: CoverageWindow
    location_id: str
    location_label: str
    destination_location_id: str
    destination_location_label: str
    required_duration_minutes: int
    capability: Literal["ALLOWED"] = "ALLOWED"


class HardUnavailableCareWindow(ContractModel):
    """One authoritative interval that cannot be assigned to a parent."""

    person_id: str
    window: CoverageWindow
    reason: str
    event_id: str


class FeasibleAssignmentMatrix(ContractModel):
    """Normalized feasible primitives derived from authoritative initial facts."""

    required_coverage_window: CoverageWindow
    people: list[FeasiblePersonAssignment]
    care_primitives: list[FeasibleCarePrimitive]
    transport_primitives: list[FeasibleTransportPrimitive]
    hard_unavailable_care_windows: list[HardUnavailableCareWindow]
    excluded_person_ids: list[str]
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
        if (
            self.authoritative_context is not None
            or self.feasible_assignment_matrix is None
            or self.soft_ranking_preferences is None
        ):
            raise ValueError("all Planner operations require only normalized feasibility data")
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


def _prune_to_full_coverage_paths(
    care_primitives: list[FeasibleCarePrimitive],
    transport_primitives: list[FeasibleTransportPrimitive],
    required: CoverageWindow,
    home_location_id: str,
) -> tuple[list[FeasibleCarePrimitive], list[FeasibleTransportPrimitive]]:
    """Keep only exact primitives that participate in a continuous full-window path."""

    primitives = [*care_primitives, *transport_primitives]

    def states(
        primitive: FeasibleCarePrimitive | FeasibleTransportPrimitive,
    ) -> tuple[tuple[Any, str], tuple[Any, str]]:
        destination = (
            primitive.destination_location_id
            if isinstance(primitive, FeasibleTransportPrimitive)
            else primitive.location_id
        )
        return (
            (primitive.window.start, primitive.location_id),
            (primitive.window.end, destination),
        )

    forward = {(required.start, home_location_id)}
    changed = True
    while changed:
        changed = False
        for primitive in primitives:
            start, end = states(primitive)
            if start in forward and end not in forward:
                forward.add(end)
                changed = True

    backward = {end for primitive in primitives if (end := states(primitive)[1])[0] == required.end}
    changed = True
    while changed:
        changed = False
        for primitive in primitives:
            start, end = states(primitive)
            if end in backward and start not in backward:
                backward.add(start)
                changed = True

    retained = {
        primitive.primitive_id
        for primitive in primitives
        if states(primitive)[0] in forward and states(primitive)[1] in backward
    }
    return (
        [item for item in care_primitives if item.primitive_id in retained],
        [item for item in transport_primitives if item.primitive_id in retained],
    )


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
    caregiver_care_windows: dict[str, list[CoverageWindow]] = {}
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
        caregiver_care_windows[caregiver["caregiver_id"]] = care_windows
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
    parent_care_windows: dict[str, list[CoverageWindow]] = {}
    parent_transport_windows: dict[str, list[CoverageWindow]] = {}
    hard_unavailable: list[HardUnavailableCareWindow] = []
    for parent in parents:
        events = sorted(parent["events"], key=lambda item: item["event_id"])
        blocked = [
            _window_from_values(event["starts_at"], event["ends_at"])
            for event in events
            if event["critical"] or not event["movable"]
        ]
        care_windows = _subtract_windows(required, blocked)
        parent_care_windows[parent["parent_id"]] = care_windows
        hard_unavailable.extend(
            HardUnavailableCareWindow(
                person_id=parent["parent_id"],
                window=_window_from_values(event["starts_at"], event["ends_at"]),
                reason="Protected critical or non-movable calendar commitment.",
                event_id=event["event_id"],
            )
            for event in events
            if event["critical"] or not event["movable"]
        )
        transport_windows: list[CoverageWindow] = []
        if parent["transport"]["can_transport_child"]:
            for raw_window in parent["transport"]["availability"]:
                intersection = _window_intersection(
                    CoverageWindow.model_validate(raw_window), required
                )
                if intersection is not None:
                    transport_windows.extend(_subtract_windows(intersection, blocked))
        if transport_windows:
            parent_transport_windows[parent["parent_id"]] = transport_windows
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

    home = schedule["family_home_location_id"]
    home_label = "Family home"
    transport_by_key: dict[tuple[Any, ...], FeasibleTransportPrimitive] = {}
    for caregiver in feasible_caregivers:
        caregiver_id = caregiver["caregiver_id"]
        location_id = caregiver["location_id"]
        duration = caregiver["travel_minutes_from_family_home"]
        if location_id == home or duration <= 0:
            continue
        duration_delta = timedelta(minutes=duration)
        caregiver_windows = caregiver_care_windows[caregiver_id]

        for parent_id, windows in sorted(parent_transport_windows.items()):
            for care_window in caregiver_windows:
                for origin, destination, departure, arrival in (
                    (home, location_id, care_window.start - duration_delta, care_window.start),
                    (location_id, home, care_window.end - duration_delta, care_window.end),
                ):
                    trip = CoverageWindow(start=departure, end=arrival)
                    if not any(
                        window.start <= trip.start and window.end >= trip.end for window in windows
                    ):
                        continue
                    primitive = FeasibleTransportPrimitive(
                        primitive_id=(
                            f"transport:{parent_id}:{trip.start.isoformat()}:{origin}:{destination}"
                        ),
                        assigned_person_id=parent_id,
                        source=CoverageSource.PARENT,
                        transporter_id=parent_id,
                        window=trip,
                        location_id=origin,
                        location_label=(
                            home_label if origin == home else caregiver["location_label"]
                        ),
                        destination_location_id=destination,
                        destination_location_label=(
                            home_label if destination == home else caregiver["location_label"]
                        ),
                        required_duration_minutes=duration,
                    )
                    transport_by_key[
                        (
                            parent_id,
                            trip.start,
                            trip.end,
                            origin,
                            destination,
                        )
                    ] = primitive

        caregiver_can_transport = caregiver["can_transport_child"] and (
            not caregiver["external_provider"] or policy["allow_provider_transport"]
        )
        if caregiver_can_transport:
            for care_window in caregiver_windows:
                if care_window.end - care_window.start < duration_delta:
                    continue
                trip = CoverageWindow(start=care_window.end - duration_delta, end=care_window.end)
                primitive = FeasibleTransportPrimitive(
                    primitive_id=(
                        f"transport:{caregiver_id}:{trip.start.isoformat()}:{location_id}:{home}"
                    ),
                    assigned_person_id=caregiver_id,
                    source=CoverageSource.CAREGIVER,
                    transporter_id=caregiver_id,
                    window=trip,
                    location_id=location_id,
                    location_label=caregiver["location_label"],
                    destination_location_id=home,
                    destination_location_label=home_label,
                    required_duration_minutes=duration,
                )
                transport_by_key[(caregiver_id, trip.start, trip.end, location_id, home)] = (
                    primitive
                )

    transport_primitives = sorted(
        transport_by_key.values(),
        key=lambda item: (
            item.window.start,
            item.window.end,
            item.transporter_id,
            item.location_id,
            item.destination_location_id,
        ),
    )
    care_primitives: list[FeasibleCarePrimitive] = []
    for caregiver in feasible_caregivers:
        caregiver_id = caregiver["caregiver_id"]
        for care_window in caregiver_care_windows[caregiver_id]:
            connected_departures = [
                item.window.start
                for item in transport_primitives
                if item.location_id == caregiver["location_id"]
                and item.destination_location_id == home
                and item.window.end == care_window.end
            ]
            care_end = min(connected_departures, default=care_window.end)
            if care_window.start >= care_end:
                continue
            primitive_window = CoverageWindow(start=care_window.start, end=care_end)
            care_primitives.append(
                FeasibleCarePrimitive(
                    primitive_id=f"care:{caregiver_id}:{primitive_window.start.isoformat()}",
                    assigned_person_id=caregiver_id,
                    source=CoverageSource.CAREGIVER,
                    window=primitive_window,
                    location_id=caregiver["location_id"],
                    location_label=caregiver["location_label"],
                )
            )
    for parent in parents:
        parent_id = parent["parent_id"]
        parent_trips = [
            item.window for item in transport_primitives if item.transporter_id == parent_id
        ]
        for care_window in parent_care_windows[parent_id]:
            for primitive_window in _subtract_windows(care_window, parent_trips):
                care_primitives.append(
                    FeasibleCarePrimitive(
                        primitive_id=f"care:{parent_id}:{primitive_window.start.isoformat()}",
                        assigned_person_id=parent_id,
                        source=CoverageSource.PARENT,
                        window=primitive_window,
                        location_id=home,
                        location_label=home_label,
                    )
                )
    care_primitives.sort(
        key=lambda item: (
            item.window.start,
            item.window.end,
            item.source.value,
            item.assigned_person_id,
        )
    )
    care_primitives, transport_primitives = _prune_to_full_coverage_paths(
        care_primitives,
        transport_primitives,
        required,
        home,
    )
    return FeasibleAssignmentMatrix(
        required_coverage_window=required,
        people=sorted(people, key=lambda item: (item.source.value, item.person_id)),
        care_primitives=care_primitives,
        transport_primitives=transport_primitives,
        hard_unavailable_care_windows=sorted(
            hard_unavailable,
            key=lambda item: (item.window.start, item.person_id, item.event_id),
        ),
        excluded_person_ids=sorted(unavailable),
        family_home_location_id=schedule["family_home_location_id"],
        require_trusted_caregiver=policy["require_trusted_caregiver"],
        unapproved_caregiver_allowed=policy["unapproved_caregiver_allowed"],
        minimum_handoff_minutes=policy["minimum_handoff_minutes"],
    )


def _care_primitive_summary(primitive: FeasibleCarePrimitive) -> str:
    return (
        f"CARE assigned_person_id={primitive.assigned_person_id} "
        f"start={primitive.window.start.isoformat()} end={primitive.window.end.isoformat()} "
        f"location_id={primitive.location_id}"
    )


def _transport_primitive_summary(primitive: FeasibleTransportPrimitive) -> str:
    return (
        f"TRANSPORT transporter_id={primitive.transporter_id} "
        f"start={primitive.window.start.isoformat()} end={primitive.window.end.isoformat()} "
        f"origin={primitive.location_id} destination={primitive.destination_location_id}"
    )


def _actionable_validator_feedback(
    issues: list[PlanValidationIssue],
    previous_candidate: RecoveryPlan | None,
    matrix: FeasibleAssignmentMatrix,
) -> list[PlanValidationIssue]:
    """Attach exact feasible primitives to repairable assignment/transition findings."""

    if previous_candidate is None:
        return issues
    ordered = sorted(
        previous_candidate.coverage_segments,
        key=lambda item: (item.window.start, item.window.end),
    )
    by_id = {segment.segment_id: segment for segment in ordered}
    enriched: list[PlanValidationIssue] = []
    for issue in issues:
        segment = by_id.get(issue.segment_id or "")
        alternatives: list[str] = []
        if issue.code is ValidationErrorCode.CAREGIVER_UNAVAILABLE and segment is not None:
            candidates = [
                primitive
                for primitive in matrix.care_primitives
                if primitive.window.start < segment.window.end
                and segment.window.start < primitive.window.end
            ]
            candidates.sort(
                key=lambda item: (
                    item.assigned_person_id != segment.assigned_person_id,
                    item.window.start,
                    item.assigned_person_id,
                )
            )
            alternatives = [_care_primitive_summary(item) for item in candidates[:6]]
        elif issue.code is ValidationErrorCode.LOCATION_TRANSITION_INVALID and segment is not None:
            if segment.segment_type is PlanSegmentType.CARE:
                alternatives.extend(
                    _care_primitive_summary(item)
                    for item in matrix.care_primitives
                    if item.assigned_person_id == segment.assigned_person_id
                )
                index = ordered.index(segment)
                if index > 0:
                    previous = ordered[index - 1]
                    previous_location = (
                        previous.destination_location_id
                        if previous.segment_type is PlanSegmentType.TRANSPORT
                        else previous.location_id
                    )
                    alternatives.extend(
                        _transport_primitive_summary(item)
                        for item in matrix.transport_primitives
                        if item.location_id == previous_location
                        and item.destination_location_id == segment.location_id
                    )
            else:
                alternatives.extend(
                    _transport_primitive_summary(item)
                    for item in matrix.transport_primitives
                    if item.transporter_id == segment.transporter_id
                    or (
                        item.location_id == segment.location_id
                        and item.destination_location_id == segment.destination_location_id
                    )
                )
        alternatives = list(dict.fromkeys(alternatives))[:6]
        if alternatives:
            message = f"{issue.message} Feasible alternatives: {'; '.join(alternatives)}."
            issue = issue.model_copy(
                update={
                    "message": message,
                    "suggested_alternatives": alternatives,
                }
            )
        enriched.append(issue)
    return enriched


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
    matrix = _build_feasible_assignment_matrix(authoritative_context)
    feedback = _actionable_validator_feedback(
        validator_feedback or [],
        previous_candidate,
        matrix,
    )
    return PlannerInvocationInput(
        operation=operation,
        planning_brief=brief,
        authoritative_context=None,
        feasible_assignment_matrix=matrix,
        soft_ranking_preferences=authoritative_context.family_preferences,
        previous_candidate=previous_candidate,
        validator_feedback=feedback,
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
    matrix = payload.get("feasible_assignment_matrix")
    if matrix is not None:
        matrix.pop("people", None)
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
    primitive_direction = (
        " Compose the plan only from FeasibleAssignmentMatrix care_primitives and "
        "transport_primitives. Every output segment must exactly copy all material fields from "
        "one supplied primitive: assigned_person_id, source, segment_type, start, end, location, "
        "destination, and transporter where applicable. Do not shorten, extend, combine, or "
        "invent primitives. hard_unavailable_care_windows and excluded_person_ids are absolute. "
        "SoftRankingPreferences rank feasible primitive sequences only."
    )
    return (
        f"{action} Treat the complete structured PlannerInvocationInput below as authoritative; "
        "it contains normalized deterministic feasibility and separate soft preferences. "
        "Do not depend on prior conversation for correctness. Keep validation_state "
        "NOT_VALIDATED."
        f"{primitive_direction} "
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
