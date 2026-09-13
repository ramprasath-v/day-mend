"""Phase 0 tests for DayMend domain contracts only."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models import (
    CalendarEvent,
    Caregiver,
    CoverageSource,
    CoverageWindow,
    FamilyPolicy,
    FamilyPreferences,
    PlanAssumption,
    RecoveryCase,
    RecoveryEvent,
    RecoveryEventType,
    RecoveryPlan,
    RecoveryPlanSegment,
    RecoveryStatus,
)


def utc_datetime(hour: int) -> datetime:
    return datetime(2026, 8, 27, hour, tzinfo=UTC)


def test_recovery_status_contains_expected_states() -> None:
    assert {status.value for status in RecoveryStatus} == {
        "DETECTED",
        "ASSESSING",
        "PLANNING",
        "EXECUTING",
        "WAITING_FOR_RESPONSE",
        "REPLANNING",
        "NO_RECOVERY_OPTION",
        "APPROVAL_REQUIRED",
        "RESOLVED",
        "FAILED",
    }


def test_coverage_window_requires_end_after_start() -> None:
    with pytest.raises(ValidationError, match="end must be after start"):
        CoverageWindow(start=utc_datetime(16), end=utc_datetime(8))


def test_coverage_window_requires_timezone_aware_values() -> None:
    with pytest.raises(ValidationError):
        CoverageWindow(
            start=datetime(2026, 8, 27, 8),
            end=datetime(2026, 8, 27, 16),
        )


def test_basic_recovery_plan_construction() -> None:
    gap = CoverageWindow(start=utc_datetime(8), end=utc_datetime(16))
    assumption = PlanAssumption(
        assumption_id="assumption-1",
        assumption_type="caregiver_available",
        subject_id="caregiver-1",
        relevant_window=gap,
        value=True,
    )

    plan = RecoveryPlan(
        plan_id="plan-a",
        coverage_segments=[
            RecoveryPlanSegment(
                segment_id="segment-1",
                window=gap,
                assigned_person_id="caregiver-1",
                source=CoverageSource.CAREGIVER,
                estimated_cost=Decimal("120.00"),
            )
        ],
        calendar_changes=[
            CalendarEvent(
                event_id="event-1",
                owner_id="parent-1",
                title="Move focus block",
                window=CoverageWindow(start=utc_datetime(16), end=utc_datetime(17)),
                movable=True,
            )
        ],
        estimated_cost=Decimal("120.00"),
        assumptions=[assumption],
    )

    assert plan.coverage_segments[0].assigned_person_id == "caregiver-1"
    assert plan.assumptions == [assumption]
    assert plan.estimated_cost == Decimal("120.00")


def test_recovery_case_represents_active_plan_and_event_history() -> None:
    gap = CoverageWindow(start=utc_datetime(8), end=utc_datetime(16))
    active_plan = RecoveryPlan(plan_id="plan-a")
    event = RecoveryEvent(
        event_id="recovery-event-1",
        event_type="DISRUPTION_DETECTED",
        occurred_at=utc_datetime(7),
        details={"source": "nanny_message"},
    )

    recovery_case = RecoveryCase(
        case_id="case-1",
        status=RecoveryStatus.PLANNING,
        disruption="Nanny is sick and unavailable today.",
        coverage_gap=gap,
        context_state={"parent_calendar_loaded": True},
        active_recovery_plan=active_plan,
        events=[event],
        created_at=utc_datetime(7),
        updated_at=utc_datetime(8),
    )

    assert recovery_case.active_recovery_plan == active_plan
    assert recovery_case.events == [event]
    assert recovery_case.status is RecoveryStatus.PLANNING


def test_caregiver_decline_event_requires_typed_response_context() -> None:
    gap = CoverageWindow(start=utc_datetime(10), end=utc_datetime(13))
    event = RecoveryEvent(
        event_id="grandma-declined",
        event_type=RecoveryEventType.CAREGIVER_DECLINED,
        occurred_at=utc_datetime(9),
        caregiver_id="grandma",
        relevant_window=gap,
        message="Sorry, I can't help today.",
    )

    assert event.event_type is RecoveryEventType.CAREGIVER_DECLINED
    assert event.caregiver_id == "grandma"


def test_caregiver_decline_event_rejects_missing_relevant_window() -> None:
    with pytest.raises(ValidationError, match="require caregiver_id, message, and relevant_window"):
        RecoveryEvent(
            event_id="invalid-decline",
            event_type=RecoveryEventType.CAREGIVER_DECLINED,
            occurred_at=utc_datetime(9),
            caregiver_id="grandma",
            message="No longer available.",
        )


def test_preferences_and_policy_are_separate_contracts() -> None:
    preferences = FamilyPreferences(prefer_family_first=True, prefer_fewer_handoffs=True)
    policy = FamilyPolicy(
        require_trusted_caregiver=True,
        unapproved_caregiver_allowed=False,
        automatic_spend_limit=Decimal("30"),
    )

    assert preferences.prefer_family_first is True
    assert policy.require_trusted_caregiver is True
    assert "prefer_family_first" not in FamilyPolicy.model_fields


def test_caregiver_is_authoritative_trust_source() -> None:
    caregiver = Caregiver(
        caregiver_id="grandma",
        name="Grandma",
        is_trusted=True,
        relationship="family",
    )

    assert caregiver.is_trusted is True
    assert "trusted_caregiver_ids" not in FamilyPolicy.model_fields
