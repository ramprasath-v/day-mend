"""Constraint-focused plan construction and validator-driven draft repair."""

from typing import Any, Protocol

from strands import Agent
from strands.models import BedrockModel

from app.agent.config import RecoveryAgentConfig
from app.agent.instructions import RECOVERY_AGENT_INSTRUCTIONS
from app.agent.recovery_agent import (
    MAX_PLAN_ATTEMPTS,
    InitialPlanningResult,
    ToolInvocationRecorder,
    build_planning_result,
    model_call_count,
    run_bounded_plan_attempts,
)
from app.agent.recovery_orchestrator import PlanningBrief
from app.fixtures import DemoScenario
from app.models import RecoveryPlan
from app.services import PlanValidator
from app.tools import RECOVERY_CONTEXT_TOOLS, use_scenario

CONSTRAINT_PLANNER_INSTRUCTIONS = RECOVERY_AGENT_INSTRUCTIONS.replace(
    "You are the single DayMend Recovery Agent. Your job is to propose practical childcare "
    "recovery\nplans for an initial disruption and, when application code explicitly supplies a "
    "recorded\nexternal event and updated world state, to produce a replacement plan.",
    "You are DayMend's Constraint Planner Agent. Your job is to construct practical childcare "
    "RecoveryPlan proposals from a structured PlanningBrief and authoritative context tools.",
).replace(
    "You receive only the disruption.",
    "You receive a structured PlanningBrief from the Recovery Orchestrator.",
)


class ConstraintPlannerLike(Protocol):
    """Invocation surface shared by the real Planner and narrow offline fakes."""

    def __call__(
        self,
        prompt: str,
        *,
        structured_output_model: type[RecoveryPlan] | None = None,
    ) -> Any: ...


def build_constraint_planner(
    config: RecoveryAgentConfig,
    recorder: ToolInvocationRecorder,
) -> Agent:
    """Create the real Strands Constraint Planner with all five planning context tools."""

    model = BedrockModel(
        model_id=config.model_id,
        region_name=config.region_name,
        temperature=0.0,
        max_tokens=4096,
    )
    return Agent(
        name="daymend_constraint_planner",
        description="Constructs and repairs childcare coverage-plan proposals.",
        model=model,
        tools=RECOVERY_CONTEXT_TOOLS,
        system_prompt=CONSTRAINT_PLANNER_INSTRUCTIONS,
        callback_handler=recorder,
    )


def run_constraint_planning(
    *,
    planner: ConstraintPlannerLike,
    recorder: ToolInvocationRecorder,
    brief: PlanningBrief,
    scenario: DemoScenario,
    model_id: str,
    validator: PlanValidator | None = None,
    max_attempts: int = MAX_PLAN_ATTEMPTS,
) -> InitialPlanningResult:
    """Gather planning facts once, then keep all repair feedback in the Planner session."""

    brief_json = brief.model_dump_json()
    with use_scenario(scenario):
        context_result = planner(
            "Consume this Recovery Orchestrator PlanningBrief and gather the authoritative facts "
            "needed to construct the plan. Call all five context tools once. The brief scopes the "
            "work but does not establish feasibility, exact cost, or validity. Do not return "
            "structured output yet and do not expose private reasoning. PlanningBrief: "
            + brief_json
        )
        attempts = run_bounded_plan_attempts(
            agent=planner,
            scenario=scenario,
            proposal_prompt=(
                "Using the PlanningBrief and authoritative tool results already in this Planner "
                "conversation, return one complete RecoveryPlan. Honor affected and preserved "
                "scope where feasible, while ensuring the full required coverage window is "
                "represented. Keep validation_state NOT_VALIDATED."
            ),
            validator=validator,
            max_attempts=max_attempts,
            repair_scope=f"{brief.planning_mode.value} Constraint-Planner draft",
        )

    return build_planning_result(
        success=attempts[-1].validation.valid,
        attempts=attempts,
        recorder=recorder,
        model_id=model_id,
        architecture="multi",
        orchestrator_invocation_count=1,
        planner_invocation_count=1 + len(attempts),
        model_call_count=model_call_count(context_result)
        + sum(attempt.model_call_count for attempt in attempts),
    )
