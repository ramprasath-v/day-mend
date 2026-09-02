"""Synthetic provider inventory and a realistic known-options coverage gap."""

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.fixtures.nanny_cancellation import DemoScenario
from app.models import (
    BackupCareCandidate,
    BackupCareProviderType,
    CalendarEvent,
    Caregiver,
    CoverageWindow,
    FamilyPolicy,
    FamilyPreferences,
)

PACIFIC = ZoneInfo("America/Los_Angeles")


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 27, hour, minute, tzinfo=PACIFIC)


def _window(start_hour: int, end_hour: int) -> CoverageWindow:
    return CoverageWindow(start=_at(start_hour), end=_at(end_hour))


def get_backup_care_research_scenario() -> DemoScenario:
    """Build a day where known care covers everything except 10:00–12:00."""

    return DemoScenario(
        disruption="The nanny reported sick at 07:02 and is unavailable today.",
        normal_caregiver_id="nanny",
        required_coverage=_window(8, 16),
        unavailable_caregiver_ids=("nanny",),
        parent_ids=("parent_a", "parent_b"),
        parent_events=(
            CalendarEvent(
                event_id="parent_a_customer_review",
                owner_id="parent_a",
                title="Customer review",
                window=_window(10, 12),
                critical=True,
            ),
            CalendarEvent(
                event_id="parent_b_board_update",
                owner_id="parent_b",
                title="Board update",
                window=_window(10, 12),
                critical=True,
            ),
        ),
        caregivers=(
            Caregiver(
                caregiver_id="grandma",
                name="Grandma",
                is_trusted=True,
                relationship="family",
                availability=[_window(8, 10)],
                hourly_rate=Decimal("0"),
                known_to_family=True,
                previously_used=True,
            ),
            Caregiver(
                caregiver_id="known_backup_sitter",
                name="Known backup sitter",
                is_trusted=True,
                relationship="paid_backup",
                availability=[_window(12, 16)],
                hourly_rate=Decimal("22"),
                known_to_family=True,
                previously_used=True,
            ),
        ),
        preferences=FamilyPreferences(
            prefer_family_first=True,
            prefer_fewer_handoffs=True,
            avoid_rescheduling_customer_meetings=True,
            preferred_backup_order=["grandma", "known_backup_sitter"],
            preferred_handoff_location="home",
            prefer_closer_backup_care=True,
            prefer_lower_backup_care_cost=True,
            preferred_minimum_provider_rating=Decimal("4.7"),
            prefer_meaningful_review_history=True,
            prefer_previously_used_provider=True,
        ),
        policy=FamilyPolicy(
            require_trusted_caregiver=True,
            unapproved_caregiver_allowed=False,
            automatic_spend_limit=Decimal("30"),
            minimum_handoff_minutes=0,
            require_verified_backup_provider=True,
            require_background_checked_backup_provider=True,
            require_approval_for_unfamiliar_paid_caregiver=True,
        ),
        child_age_years=4,
        backup_care_candidates=_candidate_inventory(),
    )


def _candidate_inventory() -> tuple[BackupCareCandidate, ...]:
    return (
        BackupCareCandidate(
            candidate_id="harbor_nanny_coop",
            display_name="Harbor Nanny Cooperative",
            provider_type=BackupCareProviderType.LOCAL_AGENCY,
            availability=[_window(10, 16)],
            hourly_rate=Decimal("27"),
            distance_miles=Decimal("2.2"),
            rating=Decimal("4.9"),
            review_count=127,
            verified=True,
            background_checked=True,
            minimum_child_age=1,
            maximum_child_age=12,
            source="synthetic_local_provider_inventory",
        ),
        BackupCareCandidate(
            candidate_id="willow_family_care",
            display_name="Willow Family Care",
            provider_type=BackupCareProviderType.INDEPENDENT_CAREGIVER,
            availability=[_window(9, 14)],
            hourly_rate=Decimal("31"),
            distance_miles=Decimal("1.2"),
            rating=Decimal("4.8"),
            review_count=64,
            verified=True,
            background_checked=True,
            minimum_child_age=0,
            maximum_child_age=10,
            source="synthetic_local_provider_inventory",
        ),
        BackupCareCandidate(
            candidate_id="bright_start_agency",
            display_name="Bright Start Backup Care",
            provider_type=BackupCareProviderType.LOCAL_AGENCY,
            availability=[_window(10, 12)],
            flat_rate=Decimal("58"),
            distance_miles=Decimal("3.8"),
            rating=Decimal("4.7"),
            review_count=205,
            verified=True,
            background_checked=True,
            minimum_child_age=2,
            maximum_child_age=12,
            source="synthetic_local_provider_inventory",
        ),
        BackupCareCandidate(
            candidate_id="value_sitter_collective",
            display_name="Value Sitter Collective",
            provider_type=BackupCareProviderType.INDEPENDENT_CAREGIVER,
            availability=[_window(12, 16)],
            hourly_rate=Decimal("23"),
            distance_miles=Decimal("4.5"),
            rating=Decimal("4.7"),
            review_count=205,
            verified=True,
            background_checked=True,
            minimum_child_age=0,
            maximum_child_age=12,
            source="synthetic_local_provider_inventory",
        ),
        BackupCareCandidate(
            candidate_id="neighborhood_helper",
            display_name="Neighborhood Helper",
            provider_type=BackupCareProviderType.INDEPENDENT_CAREGIVER,
            availability=[_window(9, 13)],
            hourly_rate=Decimal("21"),
            distance_miles=Decimal("0.8"),
            rating=Decimal("4.9"),
            review_count=18,
            verified=True,
            background_checked=False,
            minimum_child_age=0,
            maximum_child_age=12,
            source="synthetic_local_provider_inventory",
        ),
        BackupCareCandidate(
            candidate_id="school_age_specialist",
            display_name="School Age Specialist",
            provider_type=BackupCareProviderType.LOCAL_AGENCY,
            availability=[_window(8, 14)],
            hourly_rate=Decimal("25"),
            distance_miles=Decimal("2.8"),
            rating=Decimal("4.85"),
            review_count=91,
            verified=True,
            background_checked=True,
            minimum_child_age=5,
            maximum_child_age=13,
            source="synthetic_local_provider_inventory",
        ),
    )
