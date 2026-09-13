"""Deterministic recovery-need analysis and synthetic backup-care eligibility."""

from enum import StrEnum

from pydantic import Field

from app.fixtures import DemoScenario
from app.models import BackupCareCandidate, Caregiver, ContractModel, CoverageWindow


class BackupCareIneligibilityCode(StrEnum):
    """Hard reasons a synthetic candidate cannot be presented for ranking."""

    UNAVAILABLE = "UNAVAILABLE"
    UNVERIFIED = "UNVERIFIED"
    BACKGROUND_CHECK_REQUIRED = "BACKGROUND_CHECK_REQUIRED"
    CHILD_AGE_UNSUPPORTED = "CHILD_AGE_UNSUPPORTED"
    EXTERNAL_PROVIDERS_DISABLED = "EXTERNAL_PROVIDERS_DISABLED"


class RecoveryNeed(ContractModel):
    """Authoritative signal that known options do or do not cover the recovery window."""

    requested_windows: list[CoverageWindow] = Field(default_factory=list)
    known_options_insufficient: bool
    research_needed: bool
    already_considered_caregiver_ids: list[str] = Field(default_factory=list)


class BackupCareCandidateAssessment(ContractModel):
    """Deterministic hard-eligibility result for one inventory record."""

    candidate: BackupCareCandidate
    eligible: bool
    ineligibility_codes: list[BackupCareIneligibilityCode] = Field(default_factory=list)


class BackupCareSearchResult(ContractModel):
    """Grounding set made available to the research agent through one read-only tool."""

    requested_windows: list[CoverageWindow]
    considered_candidates: list[BackupCareCandidateAssessment]
    eligible_candidates: list[BackupCareCandidate]


def assess_known_option_recovery_need(scenario: DemoScenario) -> RecoveryNeed:
    """Find required intervals no currently known caregiver or available parent can cover."""

    required = scenario.required_coverage
    available: list[CoverageWindow] = []
    for caregiver in scenario.caregivers:
        if (
            caregiver.caregiver_id not in scenario.unavailable_caregiver_ids
            and (not caregiver.external_provider or scenario.policy.allow_external_backup_providers)
            and (
                caregiver.is_trusted
                or (
                    not scenario.policy.require_trusted_caregiver
                    and scenario.policy.unapproved_caregiver_allowed
                )
            )
        ):
            available.extend(caregiver.availability)
    for parent_id in scenario.parent_ids:
        parent_windows = [required]
        for event in scenario.parent_events:
            if event.owner_id != parent_id or (event.movable and not event.critical):
                continue
            parent_windows = [
                remainder
                for window in parent_windows
                for remainder in _subtract(window, event.window)
            ]
        available.extend(parent_windows)

    uncovered = _uncovered(required, available)
    return RecoveryNeed(
        requested_windows=uncovered,
        known_options_insufficient=bool(uncovered),
        research_needed=bool(uncovered) and scenario.policy.allow_external_backup_providers,
        already_considered_caregiver_ids=[
            caregiver.caregiver_id for caregiver in scenario.caregivers
        ],
    )


def search_backup_care_candidates(
    scenario: DemoScenario,
    requested_windows: list[CoverageWindow],
) -> BackupCareSearchResult:
    """Apply only hard policy, child-age, and full-window availability filters."""

    assessments: list[BackupCareCandidateAssessment] = []
    eligible: list[BackupCareCandidate] = []
    for candidate in scenario.backup_care_candidates:
        if not scenario.policy.allow_provider_transport:
            candidate = candidate.model_copy(update={"can_transport_child": False})
        codes: list[BackupCareIneligibilityCode] = []
        if not scenario.policy.allow_external_backup_providers:
            codes.append(BackupCareIneligibilityCode.EXTERNAL_PROVIDERS_DISABLED)
        if not all(_is_covered(window, candidate.availability) for window in requested_windows):
            codes.append(BackupCareIneligibilityCode.UNAVAILABLE)
        if scenario.policy.require_verified_backup_provider and not candidate.verified:
            codes.append(BackupCareIneligibilityCode.UNVERIFIED)
        if (
            scenario.policy.require_background_checked_backup_provider
            and not candidate.background_checked
        ):
            codes.append(BackupCareIneligibilityCode.BACKGROUND_CHECK_REQUIRED)
        if (
            not candidate.minimum_child_age
            <= scenario.child_age_years
            <= candidate.maximum_child_age
        ):
            codes.append(BackupCareIneligibilityCode.CHILD_AGE_UNSUPPORTED)
        assessment = BackupCareCandidateAssessment(
            candidate=candidate,
            eligible=not codes,
            ineligibility_codes=codes,
        )
        assessments.append(assessment)
        if assessment.eligible:
            eligible.append(candidate)
    return BackupCareSearchResult(
        requested_windows=requested_windows,
        considered_candidates=assessments,
        eligible_candidates=eligible,
    )


def add_researched_caregiver(
    scenario: DemoScenario,
    candidate: BackupCareCandidate,
) -> DemoScenario:
    """Convert one grounded recommendation into authoritative Planner/Validator context."""

    if not scenario.policy.allow_external_backup_providers:
        raise ValueError("External backup providers are disabled by family policy.")
    caregiver = Caregiver(
        caregiver_id=candidate.candidate_id,
        name=candidate.display_name,
        is_trusted=candidate.verified and candidate.background_checked,
        relationship="researched_external_backup",
        availability=candidate.availability,
        hourly_rate=candidate.hourly_rate,
        flat_rate=candidate.flat_rate,
        known_to_family=candidate.known_to_family,
        previously_used=candidate.previously_used,
        external_provider=True,
        care_location_type=candidate.care_location_type,
        location_id=candidate.location_id,
        location_label=candidate.location_label,
        travel_minutes_from_family_home=candidate.travel_minutes_from_family_home,
        can_transport_child=candidate.can_transport_child
        and scenario.policy.allow_provider_transport,
    )
    return DemoScenario(
        disruption=scenario.disruption,
        normal_caregiver_id=scenario.normal_caregiver_id,
        required_coverage=scenario.required_coverage,
        unavailable_caregiver_ids=scenario.unavailable_caregiver_ids,
        parent_ids=scenario.parent_ids,
        parent_events=scenario.parent_events,
        caregivers=(*scenario.caregivers, caregiver),
        preferences=scenario.preferences,
        policy=scenario.policy,
        family_home_location_id=scenario.family_home_location_id,
        parent_transport_capabilities=scenario.parent_transport_capabilities,
        child_age_years=scenario.child_age_years,
        backup_care_candidates=scenario.backup_care_candidates,
    )


def _uncovered(required: CoverageWindow, available: list[CoverageWindow]) -> list[CoverageWindow]:
    clipped = [
        CoverageWindow(start=max(required.start, window.start), end=min(required.end, window.end))
        for window in available
        if window.start < required.end and required.start < window.end
    ]
    merged = _merge(clipped)
    cursor = required.start
    uncovered: list[CoverageWindow] = []
    for window in merged:
        if window.start > cursor:
            uncovered.append(CoverageWindow(start=cursor, end=window.start))
        cursor = max(cursor, window.end)
    if cursor < required.end:
        uncovered.append(CoverageWindow(start=cursor, end=required.end))
    return uncovered


def _merge(windows: list[CoverageWindow]) -> list[CoverageWindow]:
    merged: list[CoverageWindow] = []
    for window in sorted(windows, key=lambda item: (item.start, item.end)):
        if not merged or window.start > merged[-1].end:
            merged.append(window)
        elif window.end > merged[-1].end:
            merged[-1] = CoverageWindow(start=merged[-1].start, end=window.end)
    return merged


def _subtract(available: CoverageWindow, blocked: CoverageWindow) -> list[CoverageWindow]:
    if available.end <= blocked.start or blocked.end <= available.start:
        return [available]
    remaining: list[CoverageWindow] = []
    if available.start < blocked.start:
        remaining.append(CoverageWindow(start=available.start, end=blocked.start))
    if blocked.end < available.end:
        remaining.append(CoverageWindow(start=blocked.end, end=available.end))
    return remaining


def _is_covered(required: CoverageWindow, availability: list[CoverageWindow]) -> bool:
    return any(
        window.start <= required.start and window.end >= required.end for window in availability
    )
