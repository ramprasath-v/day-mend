"""Orchestration tests for bounded initial-plan validation and repair."""

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.agent.recovery_agent import (
    MAX_PLAN_ATTEMPTS,
    ToolInvocationRecorder,
    run_initial_planning_session,
)
from app.fixtures import get_demo_scenario
from app.models import (
    CalendarEvent,
    CoverageSource,
    CoverageWindow,
    PlanValidationState,
    RecoveryPlan,
    RecoveryPlanSegment,
)
from app.services import PlanValidator, ValidationErrorCode

PACIFIC = ZoneInfo("America/Los_Angeles")


def window(start_hour: int, end_hour: int) -> CoverageWindow:
    return CoverageWindow(
        start=datetime(2026, 8, 27, start_hour, tzinfo=PACIFIC),
        end=datetime(2026, 8, 27, end_hour, tzinfo=PACIFIC),
    )


def segment(
    segment_id: str,
    start_hour: int,
    end_hour: int,
    person_id: str,
    source: CoverageSource,
) -> RecoveryPlanSegment:
    return RecoveryPlanSegment(
        segment_id=segment_id,
        window=window(start_hour, end_hour),
        assigned_person_id=person_id,
        source=source,
        estimated_cost=Decimal("0"),
    )


def valid_plan() -> RecoveryPlan:
    return RecoveryPlan(
        plan_id="valid-plan",
        coverage_segments=[
            segment("parent-morning", 8, 9, "parent_a", CoverageSource.PARENT),
            segment(
                "employer-care",
                9,
                16,
                "employer_backup_care",
                CoverageSource.CAREGIVER,
            ),
        ],
        calendar_changes=[
            CalendarEvent(
                event_id="parent_a_standup",
                owner_id="parent_a",
                title="Internal standup",
                window=window(16, 17),
                movable=True,
            )
        ],
    )


def unavailable_caregiver_plan() -> RecoveryPlan:
    return RecoveryPlan(
        plan_id="invalid-plan",
        coverage_segments=[
            segment(
                "too-early",
                8,
                16,
                "employer_backup_care",
                CoverageSource.CAREGIVER,
            )
        ],
    )


class StubAgent:
    """Return a narrow sequence of proposals; it is not evidence of LLM behavior."""

    def __init__(self, proposals: list[RecoveryPlan]) -> None:
        self.proposals = proposals.copy()
        self.calls: list[tuple[str, bool]] = []

    def __call__(
        self,
        prompt: str,
        *,
        structured_output_model: type[RecoveryPlan] | None = None,
    ) -> SimpleNamespace:
        self.calls.append((prompt, structured_output_model is not None))
        if structured_output_model is None:
            return SimpleNamespace(structured_output=None)
        return SimpleNamespace(structured_output=self.proposals.pop(0))


class CountingValidator(PlanValidator):
    def __init__(self) -> None:
        self.calls = 0

    def validate(self, plan, scenario):
        self.calls += 1
        return super().validate(plan, scenario)


def run(proposals: list[RecoveryPlan]):
    agent = StubAgent(proposals)
    validator = CountingValidator()
    result = run_initial_planning_session(
        agent=agent,
        recorder=ToolInvocationRecorder(),
        disruption=get_demo_scenario().disruption,
        scenario=get_demo_scenario(),
        model_id="stub-model",
        validator=validator,
    )
    return result, agent, validator


def test_first_valid_proposal_stops_after_one_attempt() -> None:
    result, agent, validator = run([valid_plan()])

    assert result.success is True
    assert result.total_attempts == 1
    assert result.final_plan is not None
    assert result.deterministic_total_cost == Decimal("48.00")
    assert validator.calls == 1
    assert len(agent.calls) == 2


def test_invalid_proposal_is_repaired_by_same_session_without_context_refetch() -> None:
    result, agent, validator = run([unavailable_caregiver_plan(), valid_plan()])

    assert result.success is True
    assert result.total_attempts == 2
    assert validator.calls == 2
    assert [structured for _, structured in agent.calls] == [False, True, True]
    repair_prompt = agent.calls[2][0]
    assert ValidationErrorCode.CAREGIVER_UNAVAILABLE.value in repair_prompt
    assert "world state and tool context have not changed" in repair_prompt
    assert "do not re-fetch all context" in repair_prompt


def test_third_proposal_can_succeed_and_no_fourth_is_requested() -> None:
    result, agent, validator = run(
        [unavailable_caregiver_plan(), unavailable_caregiver_plan(), valid_plan()]
    )

    assert result.success is True
    assert result.total_attempts == MAX_PLAN_ATTEMPTS
    assert validator.calls == MAX_PLAN_ATTEMPTS
    assert len(agent.calls) == 1 + MAX_PLAN_ATTEMPTS


def test_three_invalid_proposals_return_structured_failure_without_fourth_attempt() -> None:
    result, agent, validator = run([unavailable_caregiver_plan()] * MAX_PLAN_ATTEMPTS)

    assert result.success is False
    assert result.total_attempts == MAX_PLAN_ATTEMPTS
    assert result.final_plan is None
    assert validator.calls == MAX_PLAN_ATTEMPTS
    assert len(agent.calls) == 1 + MAX_PLAN_ATTEMPTS
    assert any(
        issue.code is ValidationErrorCode.CAREGIVER_UNAVAILABLE
        and issue.subject_id == "employer_backup_care"
        and issue.segment_id == "too-early"
        for issue in result.final_errors
    )


def test_model_claimed_validation_state_cannot_override_validator() -> None:
    claimed_valid = unavailable_caregiver_plan().model_copy(
        update={"validation_state": PlanValidationState.VALID, "validation_errors": []}
    )

    result, _, _ = run([claimed_valid] * MAX_PLAN_ATTEMPTS)

    assert result.success is False
    assert all(
        attempt.proposed_plan.validation_state is PlanValidationState.NOT_VALIDATED
        and attempt.validation.valid is False
        for attempt in result.attempts
    )


def test_initial_repair_does_not_introduce_external_state_replanning() -> None:
    _, agent, _ = run([unavailable_caregiver_plan(), valid_plan()])

    repair_prompt = agent.calls[2][0]
    assert "world state and tool context have not changed" in repair_prompt
    assert "external event" not in repair_prompt
    assert "REPLANNING" not in repair_prompt
