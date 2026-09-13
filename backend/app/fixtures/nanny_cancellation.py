"""Deterministic synthetic data for the primary nanny-cancellation scenario."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.models import (
    BackupCareCandidate,
    BackupCareProviderType,
    CalendarEvent,
    Caregiver,
    CareLocationType,
    CoverageWindow,
    FamilyPolicy,
    FamilyPreferences,
    ParentTransportCapability,
)

DEMO_TIME_ZONE = ZoneInfo("America/Los_Angeles")


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 27, hour, minute, tzinfo=DEMO_TIME_ZONE)


def _window(start_hour: int, end_hour: int, start_minute: int = 0) -> CoverageWindow:
    return CoverageWindow(start=_at(start_hour, start_minute), end=_at(end_hour))


def _range(
    start_hour: int, start_minute: int, end_hour: int, end_minute: int = 0
) -> CoverageWindow:
    return CoverageWindow(
        start=_at(start_hour, start_minute),
        end=_at(end_hour, end_minute),
    )


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
    family_home_location_id: str = "family_home"
    parent_transport_capabilities: tuple[ParentTransportCapability, ...] = ()
    child_age_years: int = 4
    backup_care_candidates: tuple[BackupCareCandidate, ...] = ()


def get_demo_scenario() -> DemoScenario:
    """Build the location-aware showcase where Grandma is a factual dependency."""

    return DemoScenario(
        disruption="The nanny reported sick at 07:02 and is unavailable today.",
        normal_caregiver_id="nanny",
        required_coverage=_window(8, 16),
        unavailable_caregiver_ids=("nanny",),
        parent_ids=("parent_a", "parent_b"),
        parent_events=(
            CalendarEvent(
                event_id="parent_a_customer_workshop",
                owner_id="parent_a",
                title="Customer workshop",
                window=_window(9, 12),
                critical=True,
            ),
            CalendarEvent(
                event_id="parent_a_afternoon_client_delivery",
                owner_id="parent_a",
                title="Afternoon client delivery",
                window=_window(12, 16),
                critical=True,
            ),
            CalendarEvent(
                event_id="parent_b_executive_presentation",
                owner_id="parent_b",
                title="Executive presentation",
                window=_range(8, 30, 12, 15),
                critical=True,
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
                availability=[_range(9, 0, 12, 15)],
                hourly_rate=Decimal("0"),
                care_location_type=CareLocationType.CAREGIVER_HOME,
                location_id="grandma_home",
                location_label="Grandma's home",
                travel_minutes_from_family_home=15,
                can_transport_child=True,
                previously_used=True,
            ),
            Caregiver(
                caregiver_id="backup_sitter",
                name="Backup sitter",
                is_trusted=True,
                relationship="paid_backup",
                availability=[_range(12, 15, 16)],
                hourly_rate=Decimal("0"),
                care_location_type=CareLocationType.FAMILY_HOME,
                known_to_family=True,
                previously_used=True,
            ),
        ),
        preferences=FamilyPreferences(
            prefer_family_first=True,
            prefer_fewer_handoffs=True,
            prefer_parent_a_morning_coverage=True,
            avoid_rescheduling_customer_meetings=True,
            preferred_backup_order=["grandma", "backup_sitter"],
            preferred_handoff_location="home",
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
        parent_transport_capabilities=(
            ParentTransportCapability(
                parent_id="parent_a",
                can_transport_child=True,
                availability=[_range(8, 45, 9)],
            ),
            ParentTransportCapability(parent_id="parent_b", can_transport_child=False),
        ),
        backup_care_candidates=(
            BackupCareCandidate(
                candidate_id="harbor_nanny_coop",
                display_name="Harbor Nanny Cooperative",
                provider_type=BackupCareProviderType.LOCAL_AGENCY,
                availability=[_range(8, 45, 12, 15)],
                hourly_rate=Decimal("27"),
                distance_miles=Decimal("2.2"),
                rating=Decimal("4.9"),
                review_count=127,
                verified=True,
                background_checked=True,
                minimum_child_age=1,
                maximum_child_age=12,
                source="synthetic_local_provider_inventory",
                care_location_type=CareLocationType.FAMILY_HOME,
            ),
            BackupCareCandidate(
                candidate_id="willow_family_care",
                display_name="Willow Family Care",
                provider_type=BackupCareProviderType.INDEPENDENT_CAREGIVER,
                availability=[_range(8, 45, 12, 15)],
                hourly_rate=Decimal("31"),
                distance_miles=Decimal("1.2"),
                rating=Decimal("4.8"),
                review_count=64,
                verified=True,
                background_checked=True,
                minimum_child_age=0,
                maximum_child_age=10,
                source="synthetic_local_provider_inventory",
                care_location_type=CareLocationType.CAREGIVER_HOME,
                location_id="willow_home",
                location_label="Willow Family Care",
                travel_minutes_from_family_home=12,
            ),
        ),
    )


def get_legacy_demo_scenario() -> DemoScenario:
    """Preserve the original all-day-option fixture for historical validator tests."""

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
                window=_range(8, 30, 10),
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
