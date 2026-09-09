"""Tests for the five read-only Strands recovery-context tools."""

import json

from app.tools import (
    get_caregivers,
    get_childcare_schedule,
    get_family_policy,
    get_family_preferences,
    get_parent_calendars,
)


def test_tools_return_json_serializable_scenario_data() -> None:
    results = [
        get_childcare_schedule(),
        get_parent_calendars(),
        get_caregivers(),
        get_family_preferences(),
        get_family_policy(),
    ]

    for result in results:
        json.dumps(result)

    assert results[0]["normal_caregiver_id"] == "nanny"
    assert results[0]["coverage_required_from"] == "2026-08-27T08:00:00-07:00"
    assert results[0]["coverage_required_to"] == "2026-08-27T16:00:00-07:00"
    assert len(results[1]["parents"]) == 2
    assert "critical=true" in results[1]["calendar_assignment_rule"]
    assert {item["caregiver_id"] for item in results[2]["caregivers"]} == {
        "grandma",
        "backup_sitter",
    }


def test_preferences_and_policy_tools_keep_soft_and_hard_rules_separate() -> None:
    preferences = get_family_preferences()
    policy = get_family_policy()

    assert preferences["prefer_family_first"] is True
    assert "require_trusted_caregiver" not in preferences
    assert policy["require_trusted_caregiver"] is True
    assert "prefer_family_first" not in policy


def test_caregiver_tool_returns_authoritative_unfiltered_trust_field() -> None:
    result = get_caregivers()
    caregivers = result["caregivers"]

    assert result["availability_is_authoritative"] is True
    assert "segment.start" in result["assignment_rule"]
    assert all("is_trusted" in caregiver for caregiver in caregivers)
    assert all("availability_windows" in caregiver for caregiver in caregivers)
    assert all(
        {"available_from", "available_to"} <= set(window)
        for caregiver in caregivers
        for window in caregiver["availability_windows"]
    )


def test_caregiver_tool_exposes_exact_demo_availability_boundaries() -> None:
    caregivers = {
        caregiver["caregiver_id"]: caregiver for caregiver in get_caregivers()["caregivers"]
    }

    assert caregivers["grandma"]["availability_windows"] == [
        {
            "available_from": "2026-08-27T09:00:00-07:00",
            "available_to": "2026-08-27T12:15:00-07:00",
        }
    ]
    assert caregivers["grandma"]["location_id"] == "grandma_home"
    assert caregivers["grandma"]["travel_minutes_from_family_home"] == 15
    assert caregivers["backup_sitter"]["availability_windows"] == [
        {
            "available_from": "2026-08-27T12:15:00-07:00",
            "available_to": "2026-08-27T16:00:00-07:00",
        }
    ]
