"""Complete in-memory Milestone 2 outcome used by Milestone 3 tests."""

from dataclasses import replace
from decimal import Decimal

from app.fixtures import get_legacy_demo_scenario
from app.models import (
    CalendarEvent,
    CoverageSource,
    FamilyPolicy,
    RecoveryPlan,
    RecoveryStatus,
)
from app.services import (
    PlanInvalidationService,
    PlanValidator,
    create_active_recovery_case,
    materialize_caregiver_assumptions,
)
from tests.milestone2_helpers import (
    at,
    grandma_decline_event,
    moved_event,
    segment,
    validated_plan_a,
)


def plan_b_proposal() -> RecoveryPlan:
    """Feasible post-decline plan with deterministic cost 48 + 44 = 92."""

    return RecoveryPlan(
        plan_id="plan-b-approval",
        coverage_segments=[
            segment("parent-morning-b", 8, 9, "parent_a", CoverageSource.PARENT),
            segment(
                "employer-midday-b",
                9,
                13,
                "employer_backup_care",
                CoverageSource.CAREGIVER,
            ),
            segment("parent-afternoon-b", 13, 14, "parent_a", CoverageSource.PARENT),
            segment(
                "sitter-afternoon-b",
                14,
                16,
                "backup_sitter",
                CoverageSource.CAREGIVER,
            ),
        ],
        calendar_changes=[
            moved_event("parent_a_standup", 7, 8),
            moved_event("parent_a_internal_sync", 14, 15),
        ],
    )


def milestone3_case() -> tuple:
    scenario = get_legacy_demo_scenario()
    initial_case = create_active_recovery_case(
        case_id="case-milestone-3",
        disruption=scenario.disruption,
        validated_plan=validated_plan_a(),
        required_coverage=scenario.required_coverage,
        now=at(7, 10),
    )
    impact = PlanInvalidationService().apply_caregiver_decline(
        initial_case,
        grandma_decline_event(),
        scenario,
    )
    validation = PlanValidator().validate(plan_b_proposal(), impact.updated_scenario)
    assert validation.valid
    assert validation.deterministic_total_cost == Decimal("92.00")
    plan_b = materialize_caregiver_assumptions(validation.validated_plan)
    assumption_ids = {assumption.assumption_id for assumption in impact.recovery_case.assumptions}
    assumptions = [
        *impact.recovery_case.assumptions,
        *[
            assumption
            for assumption in plan_b.assumptions
            if assumption.assumption_id not in assumption_ids
        ],
    ]
    recovery_case = impact.recovery_case.model_copy(
        update={
            "status": RecoveryStatus.EXECUTING,
            "active_recovery_plan": plan_b,
            "assumptions": assumptions,
            "uncovered_windows": [],
            "updated_at": at(9, 10),
        }
    )
    return recovery_case, impact.updated_scenario, validation


def twenty_dollar_case() -> tuple:
    scenario = get_legacy_demo_scenario()
    caregivers = tuple(
        caregiver.model_copy(update={"flat_rate": Decimal("20")})
        if caregiver.caregiver_id == "employer_backup_care"
        else caregiver
        for caregiver in scenario.caregivers
    )
    policy = FamilyPolicy(
        require_trusted_caregiver=True,
        unapproved_caregiver_allowed=False,
        automatic_spend_limit=Decimal("30"),
    )
    scenario = replace(scenario, caregivers=caregivers, policy=policy)
    proposal = RecoveryPlan(
        plan_id="plan-twenty",
        coverage_segments=[
            segment("parent-morning", 8, 9, "parent_a", CoverageSource.PARENT),
            segment(
                "employer-rest",
                9,
                16,
                "employer_backup_care",
                CoverageSource.CAREGIVER,
            ),
        ],
        calendar_changes=[
            CalendarEvent(
                event_id="parent_a_standup",
                owner_id="parent_a",
                title="Internal standup",
                window=moved_event("parent_a_standup", 7, 8).window,
                movable=True,
            )
        ],
    )
    validation = PlanValidator().validate(proposal, scenario)
    assert validation.valid
    assert validation.deterministic_total_cost == Decimal("20.00")
    case = create_active_recovery_case(
        case_id="case-twenty",
        disruption=scenario.disruption,
        validated_plan=validation.validated_plan,
        required_coverage=scenario.required_coverage,
        now=at(7, 10),
    )
    return case.model_copy(update={"status": RecoveryStatus.EXECUTING}), scenario, validation
