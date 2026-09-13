"""Deterministic full-day feasibility gate for grounded research candidates."""

from dataclasses import dataclass

from app.agent.backup_care_researcher import BackupCareResearchRun
from app.agent.constraint_planner import (
    FeasibleAssignmentMatrix,
    PlannerOperation,
    build_planner_invocation_input,
)
from app.agent.recovery_orchestrator import PlanningBrief, PlanningMode
from app.fixtures import DemoScenario
from app.models import BackupCareCandidate
from app.observability import log_event
from app.services import add_researched_caregiver


class NoPlanableResearchCandidateError(RuntimeError):
    """No grounded research candidate can form a complete deterministic path."""


@dataclass(frozen=True)
class PlanableResearchCandidate:
    """Highest-ranked grounded candidate that survives full-path matrix pruning."""

    candidate: BackupCareCandidate
    rank: int
    scenario: DemoScenario
    matrix: FeasibleAssignmentMatrix


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
