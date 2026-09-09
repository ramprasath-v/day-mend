"""Deterministic tests for agent-proposed recovery-plan validation."""

from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.fixtures import DemoScenario, get_legacy_demo_scenario
from app.models import (
    CalendarEvent,
    Caregiver,
    CoverageSource,
    CoverageWindow,
    FamilyPolicy,
    PlanValidationState,
    RecoveryPlan,
    RecoveryPlanSegment,
)
from app.services import PlanValidator, ValidationErrorCode

PACIFIC = ZoneInfo("America/Los_Angeles")


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 27, hour, minute, tzinfo=PACIFIC)


def window(start_hour: int, end_hour: int, start_minute: int = 0) -> CoverageWindow:
    return CoverageWindow(start=at(start_hour, start_minute), end=at(end_hour))


def segment(
    segment_id: str,
    start_hour: int,
    end_hour: int,
    person_id: str,
    source: CoverageSource,
    *,
    start_minute: int = 0,
    proposed_cost: str = "0",
) -> RecoveryPlanSegment:
    return RecoveryPlanSegment(
        segment_id=segment_id,
        window=window(start_hour, end_hour, start_minute),
        assigned_person_id=person_id,
        source=source,
        estimated_cost=Decimal(proposed_cost),
    )


def moved_standup() -> CalendarEvent:
    return CalendarEvent(
        event_id="parent_a_standup",
        owner_id="parent_a",
        title="Internal standup",
        window=window(16, 17),
        movable=True,
    )


def valid_plan(*, proposed_cost: str = "0") -> RecoveryPlan:
    return RecoveryPlan(
        plan_id="plan-a",
        coverage_segments=[
            segment("parent-morning", 8, 9, "parent_a", CoverageSource.PARENT),
            segment(
                "employer-care",
                9,
                16,
                "employer_backup_care",
                CoverageSource.CAREGIVER,
                proposed_cost=proposed_cost,
            ),
        ],
        calendar_changes=[moved_standup()],
        estimated_cost=Decimal(proposed_cost),
    )


def validate(plan: RecoveryPlan, scenario: DemoScenario | None = None):
    return PlanValidator().validate(plan, scenario or get_legacy_demo_scenario())


def test_fully_covered_plan_is_valid() -> None:
    result = validate(valid_plan(proposed_cost="48"))

    assert result.valid is True
    assert result.errors == []
    assert result.validated_plan.validation_state is PlanValidationState.VALID


def test_thirty_minute_uncovered_gap_is_invalid() -> None:
    plan = valid_plan()
    plan.coverage_segments[1] = segment(
        "employer-care",
        9,
        16,
        "employer_backup_care",
        CoverageSource.CAREGIVER,
        start_minute=30,
    )

    result = validate(plan)

    assert result.valid is False
    assert any("30 minutes" in error for error in result.errors)


def test_untrusted_caregiver_is_invalid_when_trust_is_required() -> None:
    scenario = get_legacy_demo_scenario()
    caregivers = tuple(
        caregiver.model_copy(update={"is_trusted": False})
        if caregiver.caregiver_id == "employer_backup_care"
        else caregiver
        for caregiver in scenario.caregivers
    )

    result = validate(valid_plan(), replace(scenario, caregivers=caregivers))

    assert result.valid is False
    assert any("not trusted" in error for error in result.errors)


def test_caregiver_outside_availability_is_invalid() -> None:
    plan = RecoveryPlan(
        plan_id="outside-availability",
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

    result = validate(plan)

    assert result.valid is False
    assert any("unavailable" in error for error in result.errors)
    assert any(
        issue.code is ValidationErrorCode.CAREGIVER_UNAVAILABLE
        and issue.subject_id == "employer_backup_care"
        and issue.segment_id == "too-early"
        for issue in result.issues
    )


def test_parent_assigned_during_critical_event_is_invalid() -> None:
    plan = RecoveryPlan(
        plan_id="critical-conflict",
        coverage_segments=[
            segment("parent-conflict", 8, 11, "parent_a", CoverageSource.PARENT),
            segment(
                "employer-care",
                11,
                16,
                "employer_backup_care",
                CoverageSource.CAREGIVER,
            ),
        ],
        calendar_changes=[moved_standup()],
    )

    result = validate(plan)

    assert result.valid is False
    assert any("parent_a_customer_workshop" in error for error in result.errors)
    assert any(
        issue.code is ValidationErrorCode.PARENT_CRITICAL_CONFLICT
        and issue.event_id == "parent_a_customer_workshop"
        for issue in result.issues
    )


def test_parent_movable_event_requires_a_calendar_change() -> None:
    plan = valid_plan()
    plan.calendar_changes = []

    result = validate(plan)

    assert result.valid is False
    assert any(
        issue.code is ValidationErrorCode.MOVABLE_EVENT_CHANGE_REQUIRED
        and issue.event_id == "parent_a_standup"
        and issue.segment_id == "parent-morning"
        for issue in result.issues
    )


def test_inconsistent_overlap_is_invalid() -> None:
    plan = RecoveryPlan(
        plan_id="overlap",
        coverage_segments=[
            segment("parent-morning", 8, 9, "parent_a", CoverageSource.PARENT),
            segment(
                "employer-first",
                9,
                13,
                "employer_backup_care",
                CoverageSource.CAREGIVER,
            ),
            segment(
                "sitter-overlap",
                12,
                16,
                "backup_sitter",
                CoverageSource.CAREGIVER,
                start_minute=30,
            ),
        ],
        calendar_changes=[moved_standup()],
    )

    result = validate(plan)

    assert result.valid is False
    assert any("Unexpected overlap" in error for error in result.errors)


def test_missing_required_handoff_buffer_is_invalid() -> None:
    scenario = get_legacy_demo_scenario()
    policy = scenario.policy.model_copy(update={"minimum_handoff_minutes": 15})

    result = validate(valid_plan(), replace(scenario, policy=policy))

    assert result.valid is False
    assert any("required buffer minutes" in error for error in result.errors)


def test_cost_is_recomputed_instead_of_trusting_proposal() -> None:
    result = validate(valid_plan(proposed_cost="1"))

    assert result.deterministic_total_cost == Decimal("48.00")
    assert result.validated_plan.estimated_cost == Decimal("48.00")
    assert result.validated_plan.coverage_segments[1].estimated_cost == Decimal("48.00")
    assert any("Recomputed plan total" in warning for warning in result.warnings)


def test_invented_caregiver_is_invalid() -> None:
    plan = RecoveryPlan(
        plan_id="invented",
        coverage_segments=[segment("invented", 8, 16, "made_up_person", CoverageSource.CAREGIVER)],
    )

    result = validate(plan)

    assert result.valid is False
    assert any("unsupported caregiver" in error for error in result.errors)


def test_soft_preference_violation_does_not_invalidate_plan() -> None:
    result = validate(valid_plan(proposed_cost="48"))

    assert result.valid is True
    assert any("soft preference" in warning for warning in result.warnings)


def test_unapproved_caregiver_policy_is_enforced_even_when_trust_not_required() -> None:
    scenario = get_legacy_demo_scenario()
    untrusted = Caregiver(
        caregiver_id="unapproved_neighbor",
        name="Unapproved neighbor",
        is_trusted=False,
        availability=[window(8, 16)],
        hourly_rate=Decimal("0"),
    )
    policy = FamilyPolicy(
        require_trusted_caregiver=False,
        unapproved_caregiver_allowed=False,
        automatic_spend_limit=Decimal("30"),
    )
    modified = replace(
        scenario,
        caregivers=scenario.caregivers + (untrusted,),
        policy=policy,
    )
    plan = RecoveryPlan(
        plan_id="hard-policy-violation",
        coverage_segments=[
            segment(
                "unapproved",
                8,
                16,
                "unapproved_neighbor",
                CoverageSource.CAREGIVER,
            )
        ],
    )

    result = validate(plan, modified)

    assert result.valid is False
    assert any("not trusted/approved" in error for error in result.errors)


def test_spend_threshold_is_reported_without_implementing_approval_flow() -> None:
    result = validate(valid_plan(proposed_cost="48"))

    assert result.valid is True
    assert result.errors == []
    assert result.deterministic_total_cost == Decimal("48.00")
    assert result.requires_approval is True
    assert any("automatic-spend limit" in warning for warning in result.warnings)


def test_feasible_plan_below_spend_threshold_does_not_require_approval() -> None:
    scenario = get_legacy_demo_scenario()
    caregivers = tuple(
        caregiver.model_copy(update={"flat_rate": Decimal("20")})
        if caregiver.caregiver_id == "employer_backup_care"
        else caregiver
        for caregiver in scenario.caregivers
    )

    result = validate(
        valid_plan(proposed_cost="20"),
        replace(scenario, caregivers=caregivers),
    )

    assert result.valid is True
    assert result.errors == []
    assert result.deterministic_total_cost == Decimal("20.00")
    assert result.requires_approval is False


def test_coverage_cannot_be_sacrificed_to_stay_under_spend_threshold() -> None:
    plan = RecoveryPlan(
        plan_id="cheap-but-uncovered",
        coverage_segments=[
            segment("parent-morning", 8, 9, "parent_a", CoverageSource.PARENT),
            segment("grandma", 10, 13, "grandma", CoverageSource.CAREGIVER),
            segment("parent-afternoon", 13, 16, "parent_a", CoverageSource.PARENT),
        ],
        calendar_changes=[
            moved_standup(),
            CalendarEvent(
                event_id="parent_a_internal_sync",
                owner_id="parent_a",
                title="Internal sync",
                window=window(17, 18),
                movable=True,
            ),
        ],
        estimated_cost=Decimal("0"),
    )

    result = validate(plan)

    assert result.deterministic_total_cost == Decimal("0.00")
    assert result.requires_approval is False
    assert result.valid is False
    assert any("Uncovered gap" in error for error in result.errors)
