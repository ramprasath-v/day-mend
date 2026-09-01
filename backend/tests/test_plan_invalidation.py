"""Deterministic tests for caregiver-decline world-state invalidation."""

from app.fixtures import get_demo_scenario
from app.models import PlanAssumptionStatus, PlanValidationState, RecoveryStatus
from app.services import (
    PlanInvalidationService,
    PlanValidator,
    ValidationErrorCode,
    create_active_recovery_case,
)
from app.tools import get_caregivers, use_scenario
from tests.milestone2_helpers import at, grandma_decline_event, validated_plan_a, window


def recovery_case():
    scenario = get_demo_scenario()
    return create_active_recovery_case(
        case_id="case-1",
        disruption=scenario.disruption,
        validated_plan=validated_plan_a(),
        required_coverage=scenario.required_coverage,
        now=at(7, 10),
    )


def test_decline_invalidates_only_matching_assumption_and_records_event() -> None:
    event = grandma_decline_event()
    outcome = PlanInvalidationService().apply_caregiver_decline(
        recovery_case(), event, get_demo_scenario()
    )

    assert len(outcome.invalidated_assumptions) == 1
    invalidated = outcome.invalidated_assumptions[0]
    assert invalidated.subject_id == "grandma"
    assert invalidated.relevant_window == window(10, 13)
    assert invalidated.status is PlanAssumptionStatus.INVALIDATED
    assert invalidated.invalidated_at == event.occurred_at
    assert invalidated.invalidation_reason == "Sorry, I can't help today."
    assert invalidated.triggering_event_id == event.event_id
    assert all(
        assumption.status is PlanAssumptionStatus.ACTIVE
        for assumption in outcome.recovery_case.assumptions
        if assumption.subject_id != "grandma"
    )
    assert outcome.recovery_case.events[-1] == event
    assert outcome.recovery_case.latest_replan_trigger_event_id == event.event_id
    assert outcome.recovery_case.status is RecoveryStatus.REPLANNING


def test_impact_analysis_identifies_broken_window_and_preserves_other_segments() -> None:
    outcome = PlanInvalidationService().apply_caregiver_decline(
        recovery_case(), grandma_decline_event(), get_demo_scenario()
    )

    assert [segment.segment_id for segment in outcome.impacted_segments] == ["grandma-midday"]
    assert list(outcome.uncovered_windows) == [window(10, 13)]
    assert {segment.segment_id for segment in outcome.preserved_segments} == {
        "parent-morning",
        "employer-morning",
        "parent-afternoon",
        "sitter-afternoon",
    }
    assert outcome.recovery_case.uncovered_windows == [window(10, 13)]


def test_updated_world_state_is_visible_to_tools_and_validator() -> None:
    scenario = get_demo_scenario()
    outcome = PlanInvalidationService().apply_caregiver_decline(
        recovery_case(), grandma_decline_event(), scenario
    )

    with use_scenario(outcome.updated_scenario):
        caregivers = {
            caregiver["caregiver_id"]: caregiver for caregiver in get_caregivers()["caregivers"]
        }
    assert caregivers["grandma"]["availability_windows"] == []
    validation = PlanValidator().validate(validated_plan_a(), outcome.updated_scenario)
    assert validation.valid is False
    assert any(
        issue.code is ValidationErrorCode.CAREGIVER_UNAVAILABLE and issue.subject_id == "grandma"
        for issue in validation.issues
    )
    assert outcome.updated_scenario.preferences == scenario.preferences
    assert outcome.updated_scenario.policy == scenario.policy


def test_original_valid_plan_is_preserved_before_replanning() -> None:
    outcome = PlanInvalidationService().apply_caregiver_decline(
        recovery_case(), grandma_decline_event(), get_demo_scenario()
    )

    assert outcome.original_valid_plan.validation_state is PlanValidationState.VALID
    assert outcome.recovery_case.previous_plans[-1].plan_id == "plan-a"
    assert outcome.recovery_case.previous_plans[-1].validation_state is PlanValidationState.VALID
    assert outcome.recovery_case.active_recovery_plan is not None
    assert (
        outcome.recovery_case.active_recovery_plan.validation_state is PlanValidationState.INVALID
    )
