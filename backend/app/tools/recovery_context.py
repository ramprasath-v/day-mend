"""Read-only Strands tools for the synthetic Milestone 1 scenario."""

from typing import Any

from strands import tool

from app.fixtures import get_demo_scenario


@tool
def get_childcare_schedule() -> dict[str, Any]:
    """Get normal childcare, the required coverage window, and today's disruption.

    Returns:
        JSON-serializable authoritative childcare schedule and unavailability facts.
    """

    scenario = get_demo_scenario()
    return {
        "normal_caregiver_id": scenario.normal_caregiver_id,
        "coverage_required_from": scenario.required_coverage.start.isoformat(),
        "coverage_required_to": scenario.required_coverage.end.isoformat(),
        "coverage_rule": (
            "Every minute from coverage_required_from to coverage_required_to must be covered."
        ),
        "disruption": scenario.disruption,
        "unavailable_caregiver_ids": list(scenario.unavailable_caregiver_ids),
    }


@tool
def get_parent_calendars() -> dict[str, Any]:
    """Get both parents' events, including time windows and critical/movable metadata.

    Returns:
        JSON-serializable parent identifiers and calendar events for the recovery date.
    """

    scenario = get_demo_scenario()
    return {
        "calendar_assignment_rule": (
            "A parent segment cannot overlap an event with critical=true or movable=false. "
            "An overlapping movable event requires a non-overlapping calendar change."
        ),
        "parents": [
            {
                "parent_id": parent_id,
                "events": [
                    {
                        "event_id": event.event_id,
                        "title": event.title,
                        "starts_at": event.window.start.isoformat(),
                        "ends_at": event.window.end.isoformat(),
                        "critical": event.critical,
                        "movable": event.movable,
                        "location": event.location,
                    }
                    for event in scenario.parent_events
                    if event.owner_id == parent_id
                ],
            }
            for parent_id in scenario.parent_ids
        ],
    }


@tool
def get_caregivers() -> dict[str, Any]:
    """Get raw caregiver trust, availability, pricing, and handoff facts.

    The result is not pre-filtered; deterministic validation remains authoritative.

    Returns:
        JSON-serializable caregiver records available to the recovery planner.
    """

    scenario = get_demo_scenario()
    return {
        "availability_is_authoritative": True,
        "assignment_rule": (
            "For one availability window, segment.start must be >= available_from and "
            "segment.end must be <= available_to."
        ),
        "caregivers": [
            {
                "caregiver_id": caregiver.caregiver_id,
                "name": caregiver.name,
                "is_trusted": caregiver.is_trusted,
                "relationship": caregiver.relationship,
                "availability_windows": [
                    {
                        "available_from": window.start.isoformat(),
                        "available_to": window.end.isoformat(),
                    }
                    for window in caregiver.availability
                ],
                "hourly_rate": str(caregiver.hourly_rate)
                if caregiver.hourly_rate is not None
                else None,
                "flat_rate": str(caregiver.flat_rate) if caregiver.flat_rate is not None else None,
                "handoff_buffer_minutes": caregiver.handoff_buffer_minutes,
            }
            for caregiver in scenario.caregivers
        ],
    }


@tool
def get_family_preferences() -> dict[str, Any]:
    """Get soft family priorities used only to rank otherwise valid recovery plans.

    Returns:
        JSON-serializable soft preferences; these are not hard validation rules.
    """

    return get_demo_scenario().preferences.model_dump(mode="json")


@tool
def get_family_policy() -> dict[str, Any]:
    """Get hard safety rules and autonomy thresholds for deterministic evaluation.

    The automatic-spend limit is an approval boundary, not a planning budget. A feasible plan
    may exceed it and then require approval before future execution.

    Returns:
        JSON-serializable policy values, including trust rules and the autonomy threshold.
    """

    return get_demo_scenario().policy.model_dump(mode="json")


RECOVERY_CONTEXT_TOOLS = [
    get_childcare_schedule,
    get_parent_calendars,
    get_caregivers,
    get_family_preferences,
    get_family_policy,
]
