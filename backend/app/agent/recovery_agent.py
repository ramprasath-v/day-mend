"""Construction and bounded invocation of the one Strands Recovery Agent."""

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

from pydantic import Field
from strands import Agent
from strands.models import BedrockModel

from app.agent.config import RecoveryAgentConfig
from app.agent.instructions import RECOVERY_AGENT_INSTRUCTIONS
from app.fixtures import DemoScenario, get_demo_scenario
from app.models import ContractModel, PlanValidationState, RecoveryPlan
from app.services import PlanValidationIssue, PlanValidationResult, PlanValidator
from app.tools import RECOVERY_CONTEXT_TOOLS, use_scenario

MAX_PLAN_ATTEMPTS = 3
RECOVERY_CONTEXT_TOOL_NAMES = {tool.tool_name for tool in RECOVERY_CONTEXT_TOOLS}


class RecoveryAgentLike(Protocol):
    """Small invocation surface used by Strands and narrow orchestration test doubles."""

    def __call__(
        self,
        prompt: str,
        *,
        structured_output_model: type[RecoveryPlan] | None = None,
    ) -> Any: ...


@dataclass
class ToolInvocationRecorder:
    """Capture observable tool names without recording model reasoning or tool payloads."""

    tool_names: list[str] = field(default_factory=list)
    _tool_use_ids: set[str] = field(default_factory=set)

    def __call__(self, **event: Any) -> None:
        tool_use = event.get("current_tool_use")
        if not isinstance(tool_use, dict) or not tool_use.get("name"):
            return
        tool_name = str(tool_use["name"])
        if tool_name not in RECOVERY_CONTEXT_TOOL_NAMES:
            return
        tool_use_id = str(tool_use.get("toolUseId", ""))
        if tool_use_id and tool_use_id in self._tool_use_ids:
            return
        if tool_use_id:
            self._tool_use_ids.add(tool_use_id)
        self.tool_names.append(tool_name)


class PlanningAttempt(ContractModel):
    """One agent proposal and its authoritative deterministic validation."""

    attempt_number: int = Field(ge=1, le=MAX_PLAN_ATTEMPTS)
    proposed_plan: RecoveryPlan
    validation: PlanValidationResult


class InitialPlanningResult(ContractModel):
    """Complete observable outcome of the bounded initial-planning session."""

    success: bool
    total_attempts: int = Field(ge=1, le=MAX_PLAN_ATTEMPTS)
    model_id: str
    tools_used: list[str] = Field(default_factory=list)
    attempts: list[PlanningAttempt]
    final_plan: RecoveryPlan | None = None
    deterministic_total_cost: Decimal = Field(ge=0)
    requires_approval: bool
    final_errors: list[PlanValidationIssue] = Field(default_factory=list)


def build_recovery_agent(
    config: RecoveryAgentConfig,
    recorder: ToolInvocationRecorder,
) -> Agent:
    """Create the single Recovery Agent backed by Amazon Bedrock."""

    model = BedrockModel(
        model_id=config.model_id,
        region_name=config.region_name,
        temperature=0.0,
        max_tokens=4096,
    )
    return Agent(
        name="daymend_recovery_agent",
        description="Creates childcare disruption recovery-plan proposals.",
        model=model,
        tools=RECOVERY_CONTEXT_TOOLS,
        system_prompt=RECOVERY_AGENT_INSTRUCTIONS,
        callback_handler=recorder,
    )


def run_initial_planning_session(
    *,
    agent: RecoveryAgentLike,
    recorder: ToolInvocationRecorder,
    disruption: str,
    scenario: DemoScenario,
    model_id: str,
    validator: PlanValidator | None = None,
    max_attempts: int = MAX_PLAN_ATTEMPTS,
) -> InitialPlanningResult:
    """Gather context once, then propose/validate/repair within one agent conversation."""

    if not 1 <= max_attempts <= MAX_PLAN_ATTEMPTS:
        raise ValueError(f"max_attempts must be between 1 and {MAX_PLAN_ATTEMPTS}")

    with use_scenario(scenario):
        agent(
            "Analyze this disruption and build a feasible recovery strategy: " + disruption + " "
            "Gather all required context with the five tools and complete the feasibility, cost, "
            "and autonomy checks in your instructions. Do not call the RecoveryPlan structured "
            "output tool yet. Do not expose private reasoning; finish with only a brief readiness "
            "confirmation after the analysis is complete."
        )

        attempts = run_bounded_plan_attempts(
            agent=agent,
            scenario=scenario,
            proposal_prompt=(
                "Using the authoritative tool results and completed analysis already in this "
                "conversation, return one RecoveryPlan now. Recheck exact coverage, caregiver "
                "availability, parent calendars, handoffs, identities, pricing, and autonomy "
                "before serializing it."
            ),
            validator=validator,
            max_attempts=max_attempts,
            repair_scope="initial-planning",
        )

    return _planning_result(
        success=attempts[-1].validation.valid,
        attempts=attempts,
        recorder=recorder,
        model_id=model_id,
    )


def run_initial_planning(
    disruption: str,
    scenario: DemoScenario | None = None,
    config: RecoveryAgentConfig | None = None,
    *,
    max_attempts: int = MAX_PLAN_ATTEMPTS,
) -> InitialPlanningResult:
    """Run the real single-agent bounded initial-planning workflow."""

    resolved_config = config or RecoveryAgentConfig.from_environment()
    resolved_scenario = scenario or get_demo_scenario()
    recorder = ToolInvocationRecorder()
    agent = build_recovery_agent(resolved_config, recorder)
    return run_initial_planning_session(
        agent=agent,
        recorder=recorder,
        disruption=disruption,
        scenario=resolved_scenario,
        model_id=resolved_config.model_id,
        max_attempts=max_attempts,
    )


def run_recovery_planning(
    disruption: str,
    config: RecoveryAgentConfig | None = None,
) -> InitialPlanningResult:
    """Compatibility entrypoint for the bounded initial-planning workflow."""

    return run_initial_planning(disruption, config=config)


def run_bounded_plan_attempts(
    *,
    agent: RecoveryAgentLike,
    scenario: DemoScenario,
    proposal_prompt: str,
    validator: PlanValidator | None = None,
    max_attempts: int = MAX_PLAN_ATTEMPTS,
    repair_scope: str,
) -> list[PlanningAttempt]:
    """Validate and repair draft proposals without applying another world-state change."""

    if not 1 <= max_attempts <= MAX_PLAN_ATTEMPTS:
        raise ValueError(f"max_attempts must be between 1 and {MAX_PLAN_ATTEMPTS}")
    deterministic_validator = validator or PlanValidator()
    attempts: list[PlanningAttempt] = []
    for attempt_number in range(1, max_attempts + 1):
        result = agent(proposal_prompt, structured_output_model=RecoveryPlan)
        if result.structured_output is None:
            raise RuntimeError("Strands returned no structured RecoveryPlan")
        proposed_plan = result.structured_output.model_copy(
            update={
                "validation_state": PlanValidationState.NOT_VALIDATED,
                "validation_errors": [],
            }
        )
        validation = deterministic_validator.validate(proposed_plan, scenario)
        attempts.append(
            PlanningAttempt(
                attempt_number=attempt_number,
                proposed_plan=proposed_plan,
                validation=validation,
            )
        )
        if validation.valid:
            break
        if attempt_number < max_attempts:
            proposal_prompt = _repair_prompt(
                attempt_number + 1,
                validation.issues,
                repair_scope=repair_scope,
            )
    return attempts


def _repair_prompt(
    attempt_number: int,
    issues: list[PlanValidationIssue],
    *,
    repair_scope: str,
) -> str:
    feedback = json.dumps(
        [issue.model_dump(mode="json") for issue in issues],
        separators=(",", ":"),
    )
    return (
        f"{repair_scope} proposal attempt {attempt_number - 1} was rejected by the "
        "authoritative deterministic validator. The world state and tool context have not "
        "changed since that proposal, so do not re-fetch all context. Repair the draft and "
        "return a "
        f"complete replacement RecoveryPlan for attempt {attempt_number}. Fix every structured "
        f"validation issue below; do not claim that an issue is waived or already valid. {feedback}"
    )


def _planning_result(
    *,
    success: bool,
    attempts: list[PlanningAttempt],
    recorder: ToolInvocationRecorder,
    model_id: str,
) -> InitialPlanningResult:
    last_validation = attempts[-1].validation
    return InitialPlanningResult(
        success=success,
        total_attempts=len(attempts),
        model_id=model_id,
        tools_used=recorder.tool_names.copy(),
        attempts=attempts,
        final_plan=last_validation.validated_plan if success else None,
        deterministic_total_cost=last_validation.deterministic_total_cost,
        requires_approval=last_validation.requires_approval,
        final_errors=[] if success else last_validation.issues,
    )
