"""Deterministic full-day feasibility gate for grounded research candidates."""

from dataclasses import dataclass

from app.agent.backup_care_researcher import BackupCareResearchRun
from app.agent.constraint_planner import (
    FeasibleAssignmentMatrix,
    PlannerOperation,
    build_feasible_assignment_matrix,
    build_planner_invocation_input,
)
from app.agent.recovery_orchestrator import PlanningBrief, PlanningMode
from app.fixtures import DemoScenario
from app.models import BackupCareCandidate, CoverageWindow, RecoveryPlanSegment
from app.observability import log_event
from app.services import add_researched_caregiver
from app.services.backup_care import RecoveryNeed, search_backup_care_candidates


class NoPlanableResearchCandidateError(RuntimeError):
    """No grounded research candidate can form a complete deterministic path."""


@dataclass(frozen=True)
class PlanableResearchCandidate:
    """Highest-ranked grounded candidate that survives full-path matrix pruning."""

    candidate: BackupCareCandidate
    rank: int
    scenario: DemoScenario
    matrix: FeasibleAssignmentMatrix


def planable_research_candidate_ids(
    *,
    scenario: DemoScenario,
    recovery_need: RecoveryNeed,
    affected_windows: list[CoverageWindow] | None = None,
    preserved_segments: list[RecoveryPlanSegment] | None = None,
) -> list[str]:
    """Return grounded candidates that can complete the connected path, without a model call."""

    search = search_backup_care_candidates(scenario, recovery_need.requested_windows)
    if len(search.eligible_candidates) < 2:
        # The existing research agent contract compares multiple grounded options.
        # Do not enter that workflow when its input contract cannot be satisfied.
        return []
    preserved_ids = {segment.segment_id for segment in preserved_segments or []}
    planable: list[str] = []
    for candidate in search.eligible_candidates:
        candidate_scenario = add_researched_caregiver(scenario, candidate)
        matrix = build_feasible_assignment_matrix(
            candidate_scenario,
            affected_windows=affected_windows,
            preserved_segments=preserved_segments,
        )
        primitives = [*matrix.care_primitives, *matrix.transport_primitives]
        immutable_ids = {item.primitive_id for item in primitives if item.immutable}
        if (
            primitives
            and preserved_ids <= immutable_ids
            and any(
                item.assigned_person_id == candidate.candidate_id for item in matrix.care_primitives
            )
        ):
            planable.append(candidate.candidate_id)
    return planable


def select_planable_research_candidate(
    *,
    research_run: BackupCareResearchRun,
    scenario: DemoScenario,
    brief: PlanningBrief,
) -> PlanableResearchCandidate:
    """Select the first ranked candidate with a complete preservation-safe path."""

    candidates = {
        candidate.candidate_id: candidate
        for candidate in research_run.search_result.eligible_candidates
    }
    operation = (
        PlannerOperation.INITIAL_PLANNING
        if brief.planning_mode is PlanningMode.INITIAL
        else PlannerOperation.REPLANNING
    )
    preserved_ids = {segment.segment_id for segment in brief.preserved_segments}

    for ranked in sorted(research_run.result.ranked_candidates, key=lambda item: item.rank):
        candidate = candidates[ranked.candidate_id]
        candidate_scenario = add_researched_caregiver(scenario, candidate)
        planner_input = build_planner_invocation_input(
            operation=operation,
            brief=brief,
            scenario=candidate_scenario,
        )
        matrix = planner_input.feasible_assignment_matrix
        assert matrix is not None
        primitives = [*matrix.care_primitives, *matrix.transport_primitives]
        immutable_ids = {primitive.primitive_id for primitive in primitives if primitive.immutable}
        candidate_care_survives = any(
            primitive.assigned_person_id == candidate.candidate_id
            for primitive in matrix.care_primitives
        )
        feasible = bool(primitives) and candidate_care_survives and preserved_ids <= immutable_ids
        log_event(
            "research_candidate_evaluated",
            candidate_id=candidate.candidate_id,
            rank=ranked.rank,
            feasible=feasible,
            care_primitive_count=len(matrix.care_primitives),
            transport_primitive_count=len(matrix.transport_primitives),
        )
        if feasible:
            log_event(
                "research_candidate_selected",
                candidate_id=candidate.candidate_id,
                rank=ranked.rank,
                feasible=True,
            )
            return PlanableResearchCandidate(
                candidate=candidate,
                rank=ranked.rank,
                scenario=candidate_scenario,
                matrix=matrix,
            )

    log_event(
        "research_candidates_exhausted",
        candidate_count=len(research_run.result.ranked_candidates),
        eligible_candidate_count=len(candidates),
    )
    raise NoPlanableResearchCandidateError(
        "Known and researched backup-care options cannot form a complete feasible plan."
    )
