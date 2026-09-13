"""Shared synthetic plans for Milestone 2 service and orchestration tests."""

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.fixtures import get_demo_scenario, get_legacy_demo_scenario
from app.models import (
    CalendarEvent,
    CoverageSource,
    CoverageWindow,
    PlanSegmentType,
    RecoveryEvent,
    RecoveryEventType,
    RecoveryPlan,
    RecoveryPlanSegment,
)
from app.services import PlanValidator

PACIFIC = ZoneInfo("America/Los_Angeles")


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 27, hour, minute, tzinfo=PACIFIC)


def window(start_hour: int, end_hour: int) -> CoverageWindow:
    return CoverageWindow(start=at(start_hour), end=at(end_hour))


def minute_window(
    start_hour: int, start_minute: int, end_hour: int, end_minute: int = 0
) -> CoverageWindow:
    return CoverageWindow(start=at(start_hour, start_minute), end=at(end_hour, end_minute))


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
    )


def moved_event(event_id: str, start_hour: int, end_hour: int) -> CalendarEvent:
    title = "Internal standup" if event_id == "parent_a_standup" else "Internal sync"
    return CalendarEvent(
        event_id=event_id,
        owner_id="parent_a",
        title=title,
        window=window(start_hour, end_hour),
        movable=True,
    )


def validated_plan_a() -> RecoveryPlan:
    proposal = RecoveryPlan(
        plan_id="plan-a",
        coverage_segments=[
            segment("parent-morning", 8, 9, "parent_a", CoverageSource.PARENT),
            segment("employer-morning", 9, 10, "employer_backup_care", CoverageSource.CAREGIVER),
            segment("grandma-midday", 10, 13, "grandma", CoverageSource.CAREGIVER),
            segment("parent-afternoon", 13, 14, "parent_a", CoverageSource.PARENT),
            segment("sitter-afternoon", 14, 16, "backup_sitter", CoverageSource.CAREGIVER),
        ],
        calendar_changes=[
            moved_event("parent_a_standup", 7, 8),
            moved_event("parent_a_internal_sync", 14, 15),
        ],
    )
    result = PlanValidator().validate(proposal, get_legacy_demo_scenario())
    assert result.valid
    return result.validated_plan


def valid_plan_b() -> RecoveryPlan:
    return RecoveryPlan(
        plan_id="plan-b",
        coverage_segments=[
            segment("parent-morning-b", 8, 9, "parent_a", CoverageSource.PARENT),
            segment(
                "employer-morning-b",
                9,
                10,
                "employer_backup_care",
                CoverageSource.CAREGIVER,
            ),
            segment(
                "employer-replacement-b",
                10,
                13,
                "employer_backup_care",
                CoverageSource.CAREGIVER,
            ),
            segment("parent-afternoon-b", 13, 14, "parent_a", CoverageSource.PARENT),
            segment("sitter-afternoon-b", 14, 16, "backup_sitter", CoverageSource.CAREGIVER),
        ],
        calendar_changes=[
            moved_event("parent_a_standup", 7, 8),
            moved_event("parent_a_internal_sync", 14, 15),
        ],
        estimated_cost=Decimal("48"),
    )


def grandma_decline_event() -> RecoveryEvent:
    return RecoveryEvent(
        event_id="event-grandma-declined",
        event_type=RecoveryEventType.CAREGIVER_DECLINED,
        caregiver_id="grandma",
        relevant_window=window(10, 13),
        occurred_at=at(9, 5),
        message="Sorry, I can't help today.",
    )


def showcase_plan_a() -> RecoveryPlan:
    proposal = RecoveryPlan(
        plan_id="showcase-plan-a",
        coverage_segments=[
            RecoveryPlanSegment(
                segment_id="parent-early",
                window=minute_window(8, 0, 8, 45),
                assigned_person_id="parent_a",
                source=CoverageSource.PARENT,
            ),
            RecoveryPlanSegment(
                segment_id="to-grandma",
                window=minute_window(8, 45, 9),
                assigned_person_id="parent_a",
                source=CoverageSource.PARENT,
                segment_type=PlanSegmentType.TRANSPORT,
                destination_location_id="grandma_home",
                destination_location_label="Grandma's home",
                transporter_id="parent_a",
            ),
            RecoveryPlanSegment(
                segment_id="grandma-care",
                window=window(9, 12),
                assigned_person_id="grandma",
                source=CoverageSource.CAREGIVER,
                location_id="grandma_home",
                location_label="Grandma's home",
            ),
            RecoveryPlanSegment(
                segment_id="grandma-to-home",
                window=minute_window(12, 0, 12, 15),
                assigned_person_id="grandma",
                source=CoverageSource.CAREGIVER,
                segment_type=PlanSegmentType.TRANSPORT,
                location_id="grandma_home",
                location_label="Grandma's home",
                destination_location_id="family_home",
                destination_location_label="Family home",
                transporter_id="grandma",
            ),
            RecoveryPlanSegment(
                segment_id="sitter-late",
                window=minute_window(12, 15, 16),
                assigned_person_id="backup_sitter",
                source=CoverageSource.CAREGIVER,
            ),
        ],
    )
    result = PlanValidator().validate(proposal, get_demo_scenario())
    assert result.valid
    return result.validated_plan
