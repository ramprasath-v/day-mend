"""Deterministic synthetic data for the primary nanny-cancellation scenario."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.fixtures.demo_date import DemoTimeline, resolve_demo_care_date
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


def get_demo_scenario(care_date: date | None = None) -> DemoScenario:
    """Build the location-aware showcase where Grandma is a factual dependency."""

    timeline = DemoTimeline(care_date or resolve_demo_care_date())

    return DemoScenario(
        disruption="The nanny reported sick at 07:02 and is unavailable today.",
        normal_caregiver_id="nanny",
        required_coverage=timeline.window(8, 16),
        unavailable_caregiver_ids=("nanny",),
        parent_ids=("parent_a", "parent_b"),
        parent_events=(
            CalendarEvent(
                event_id="parent_a_customer_workshop",
                owner_id="parent_a",
                title="Customer workshop",
                window=timeline.window(9, 12),
                critical=True,
            ),
            CalendarEvent(
                event_id="parent_a_afternoon_client_delivery",
                owner_id="parent_a",
                title="Afternoon client delivery",
                window=timeline.window(12, 16),
                critical=True,
            ),
            CalendarEvent(
                event_id="parent_b_executive_presentation",
                owner_id="parent_b",
                title="Executive presentation",
                window=timeline.window(8, 12, 30, 15),
                critical=True,
            ),
            CalendarEvent(
                event_id="parent_b_interview",
                owner_id="parent_b",
                title="Interview",
                window=timeline.window(14, 15),
                critical=True,
            ),
        ),
        caregivers=(
            Caregiver(
                caregiver_id="grandma",
                name="Grandma",
                is_trusted=True,
                relationship="family",
                availability=[timeline.window(9, 12, 0, 15)],
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
                availability=[timeline.window(12, 16, 15)],
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
                availability=[timeline.window(8, 9, 45)],
            ),
            ParentTransportCapability(parent_id="parent_b", can_transport_child=False),
        ),
        backup_care_candidates=(
            BackupCareCandidate(
                candidate_id="harbor_nanny_coop",
                display_name="Harbor Nanny Cooperative",
                provider_type=BackupCareProviderType.LOCAL_AGENCY,
                availability=[timeline.window(8, 12, 45, 15)],
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
                availability=[timeline.window(8, 12, 45, 15)],
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


def get_legacy_demo_scenario(care_date: date | None = None) -> DemoScenario:
    """Preserve the original all-day-option fixture for historical validator tests."""

    timeline = DemoTimeline(care_date or resolve_demo_care_date())

    return DemoScenario(
        disruption="The nanny reported sick at 07:02 and is unavailable today.",
        normal_caregiver_id="nanny",
        required_coverage=timeline.window(8, 16),
        unavailable_caregiver_ids=("nanny",),
        parent_ids=("parent_a", "parent_b"),
        parent_events=(
            CalendarEvent(
                event_id="parent_a_standup",
                owner_id="parent_a",
                title="Internal standup",
                window=timeline.window(8, 9),
                movable=True,
            ),
            CalendarEvent(
                event_id="parent_a_customer_workshop",
                owner_id="parent_a",
                title="Customer workshop",
                window=timeline.window(9, 11),
                critical=True,
            ),
            CalendarEvent(
                event_id="parent_a_internal_sync",
                owner_id="parent_a",
                title="Internal sync",
                window=timeline.window(13, 14),
                movable=True,
            ),
            CalendarEvent(
                event_id="parent_b_executive_presentation",
                owner_id="parent_b",
                title="Executive presentation",
                window=timeline.window(8, 10, 30),
                critical=True,
            ),
            CalendarEvent(
                event_id="parent_b_focus_block",
                owner_id="parent_b",
                title="Focus block",
                window=timeline.window(11, 12),
                movable=True,
            ),
            CalendarEvent(
                event_id="parent_b_interview",
                owner_id="parent_b",
                title="Interview",
                window=timeline.window(14, 15),
                critical=True,
            ),
        ),
        caregivers=(
            Caregiver(
                caregiver_id="grandma",
                name="Grandma",
                is_trusted=True,
                relationship="family",
                availability=[timeline.window(10, 13)],
                hourly_rate=Decimal("0"),
            ),
            Caregiver(
                caregiver_id="backup_sitter",
                name="Backup sitter",
                is_trusted=True,
                relationship="paid_backup",
                availability=[timeline.window(12, 16)],
                hourly_rate=Decimal("22"),
            ),
            Caregiver(
                caregiver_id="employer_backup_care",
                name="Employer backup care",
                is_trusted=True,
                relationship="employer_benefit",
                availability=[timeline.window(9, 16)],
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
