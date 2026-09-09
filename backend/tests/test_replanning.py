"""Orchestration tests for external-event replanning and bounded Plan B repair."""

import inspect
from types import SimpleNamespace

from app.agent.recovery_agent import MAX_PLAN_ATTEMPTS, ToolInvocationRecorder
from app.agent.replanning import process_external_event
from app.fixtures import get_legacy_demo_scenario
from app.models import PlanValidationState, RecoveryPlan, RecoveryStatus
from app.services import PlanValidator, ValidationErrorCode, create_active_recovery_case
from tests.milestone2_helpers import (
    at,
    grandma_decline_event,
    valid_plan_b,
    validated_plan_a,
)


class StubAgent:
    """Return supplied Plan B drafts; this tests orchestration, not LLM behavior."""

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


def active_case():
    scenario = get_legacy_demo_scenario()
    return create_active_recovery_case(
        case_id="case-replan",
        disruption=scenario.disruption,
        validated_plan=validated_plan_a(),
        required_coverage=scenario.required_coverage,
        now=at(7, 10),
    )


def run_replan(proposals: list[RecoveryPlan]):
    agent = StubAgent(proposals)
    validator = CountingValidator()
    result = process_external_event(
        recovery_case=active_case(),
        event=grandma_decline_event(),
        scenario=get_legacy_demo_scenario(),
        agent=agent,
        recorder=ToolInvocationRecorder(),
        validator=validator,
    )
    return result, agent, validator


def test_invalid_plan_b_uses_bounded_repair_then_valid_plan_becomes_active() -> None:
    result, agent, validator = run_replan([validated_plan_a(), valid_plan_b()])

    assert result.success is True
    assert result.total_attempts == 2
    assert validator.calls == 2
    assert [structured for _, structured in agent.calls] == [False, True, True]
    assert '"grandma":[]' in agent.calls[0][0]
    assert ValidationErrorCode.CAREGIVER_UNAVAILABLE.value in agent.calls[2][0]
    assert result.final_validation.valid is True
    assert result.final_plan is not None
    assert all(
        segment.assigned_person_id != "grandma" for segment in result.final_plan.coverage_segments
    )
    assert result.recovery_case.active_recovery_plan == result.final_plan
    assert result.recovery_case.active_recovery_plan.validation_state is PlanValidationState.VALID
    assert result.recovery_case.status is RecoveryStatus.EXECUTING
    assert result.status_history == [
        RecoveryStatus.WAITING_FOR_RESPONSE,
        RecoveryStatus.REPLANNING,
        RecoveryStatus.EXECUTING,
    ]


def test_success_preserves_plan_a_event_and_invalidation_history() -> None:
    result, _, _ = run_replan([valid_plan_b()])

    assert [plan.plan_id for plan in result.recovery_case.previous_plans] == ["plan-a"]
    assert result.recovery_case.previous_plans[0].validation_state is PlanValidationState.VALID
    assert result.recovery_case.events == [grandma_decline_event()]
    assert result.invalidated_assumptions[0].triggering_event_id == "event-grandma-declined"
    assert [segment.segment_id for segment in result.impacted_segments] == ["grandma-midday"]
    assert len(result.preserved_segments) == 4


def test_three_invalid_plan_b_drafts_return_failure_without_activating_one() -> None:
    result, agent, validator = run_replan([validated_plan_a()] * MAX_PLAN_ATTEMPTS)

    assert result.success is False
    assert result.total_attempts == MAX_PLAN_ATTEMPTS
    assert validator.calls == MAX_PLAN_ATTEMPTS
    assert len(agent.calls) == 1 + MAX_PLAN_ATTEMPTS
    assert result.final_plan is None
    assert result.recovery_case.status is RecoveryStatus.REPLANNING
    assert result.recovery_case.active_recovery_plan is not None
    assert result.recovery_case.active_recovery_plan.plan_id == "plan-a"
    assert result.recovery_case.previous_plans[0].validation_state is PlanValidationState.VALID
    assert all(
        issue.code is ValidationErrorCode.CAREGIVER_UNAVAILABLE
        for issue in result.final_errors
        if issue.subject_id == "grandma"
    )


def test_replanning_code_contains_no_caregiver_to_replacement_branch() -> None:
    source = inspect.getsource(process_external_event)

    assert "employer_backup_care" not in source
    assert "backup_sitter" not in source
    assert "grandma" not in source.lower()
