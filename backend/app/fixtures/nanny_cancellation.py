"""Deterministic synthetic data for the primary nanny-cancellation scenario."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.models import (
    CalendarEvent,
    Caregiver,
    CoverageWindow,
    FamilyPolicy,
    FamilyPreferences,
)

DEMO_TIME_ZONE = ZoneInfo("America/Los_Angeles")


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 27, hour, minute, tzinfo=DEMO_TIME_ZONE)


def _window(start_hour: int, end_hour: int, start_minute: int = 0) -> CoverageWindow:
    return CoverageWindow(start=_at(start_hour, start_minute), end=_at(end_hour))


@dataclass(frozen=True)
class DemoScenario:
    """All authoritative facts available through the five read-only tools."""

    disruption: str
    normal_caregiver_id: str
    required_coverage: CoverageWindow
    unavailable_caregiver_ids: tuple[str, ...]
    parent_ids: tuple[str, ...]
    parent_events: tuple[CalendarEvent, ...]
    caregivers: tuple[Caregiver, ...]
    preferences: FamilyPreferences
    policy: FamilyPolicy


def get_demo_scenario() -> DemoScenario:
    """Build a fresh copy of the synthetic Milestone 1 scenario."""

    return DemoScenario(
        disruption="The nanny reported sick at 07:02 and is unavailable today.",
        normal_caregiver_id="nanny",
        required_coverage=_window(8, 16),
        unavailable_caregiver_ids=("nanny",),
        parent_ids=("parent_a", "parent_b"),
        parent_events=(
            CalendarEvent(
                event_id="parent_a_standup",
                owner_id="parent_a",
                title="Internal standup",
                window=_window(8, 9),
                movable=True,
            ),
            CalendarEvent(
                event_id="parent_a_customer_workshop",
                owner_id="parent_a",
                title="Customer workshop",
                window=_window(9, 11),
                critical=True,
            ),
            CalendarEvent(
                event_id="parent_a_internal_sync",
                owner_id="parent_a",
                title="Internal sync",
                window=_window(13, 14),
                movable=True,
            ),
            CalendarEvent(
                event_id="parent_b_executive_presentation",
                owner_id="parent_b",
                title="Executive presentation",
                window=CoverageWindow(start=_at(8, 30), end=_at(10)),
                critical=True,
            ),
            CalendarEvent(
                event_id="parent_b_focus_block",
                owner_id="parent_b",
                title="Focus block",
                window=_window(11, 12),
                movable=True,
            ),
            CalendarEvent(
                event_id="parent_b_interview",
                owner_id="parent_b",
                title="Interview",
                window=_window(14, 15),
                critical=True,
            ),
        ),
        caregivers=(
            Caregiver(
                caregiver_id="grandma",
                name="Grandma",
                is_trusted=True,
                relationship="family",
                availability=[_window(10, 13)],
                hourly_rate=Decimal("0"),
            ),
            Caregiver(
                caregiver_id="backup_sitter",
                name="Backup sitter",
                is_trusted=True,
                relationship="paid_backup",
                availability=[_window(12, 16)],
                hourly_rate=Decimal("22"),
            ),
            Caregiver(
                caregiver_id="employer_backup_care",
                name="Employer backup care",
                is_trusted=True,
                relationship="employer_benefit",
                availability=[_window(9, 16)],
                flat_rate=Decimal("48"),
            ),
        ),
        preferences=FamilyPreferences(
            prefer_family_first=True,
            prefer_fewer_handoffs=True,
            prefer_parent_a_morning_coverage=True,
            avoid_rescheduling_customer_meetings=True,
            preferred_backup_order=["grandma", "backup_sitter", "employer_backup_care"],
            preferred_handoff_location="home",
        ),
        policy=FamilyPolicy(
            require_trusted_caregiver=True,
            unapproved_caregiver_allowed=False,
            automatic_spend_limit=Decimal("30"),
            minimum_handoff_minutes=0,
        ),
    )
