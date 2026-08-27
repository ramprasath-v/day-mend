"""Offline checks for the real-agent configuration boundary."""

from app.agent.config import DEFAULT_BEDROCK_MODEL_ID, RecoveryAgentConfig
from app.agent.instructions import RECOVERY_AGENT_INSTRUCTIONS
from app.agent.recovery_agent import ToolInvocationRecorder
from app.models import PlanValidationState, RecoveryPlan
from app.tools import RECOVERY_CONTEXT_TOOLS


def test_agent_uses_one_configurable_bedrock_model(monkeypatch) -> None:
    monkeypatch.setenv("DAYMEND_BEDROCK_MODEL_ID", "test.model-id")
    monkeypatch.setenv("AWS_REGION", "us-west-2")

    config = RecoveryAgentConfig.from_environment()

    assert config.model_id == "test.model-id"
    assert config.region_name == "us-west-2"
    assert DEFAULT_BEDROCK_MODEL_ID == "global.anthropic.claude-sonnet-4-6"


def test_agent_has_exactly_the_five_context_tools() -> None:
    assert [tool.tool_name for tool in RECOVERY_CONTEXT_TOOLS] == [
        "get_childcare_schedule",
        "get_parent_calendars",
        "get_caregivers",
        "get_family_preferences",
        "get_family_policy",
    ]


def test_agent_instructions_preserve_validation_boundary() -> None:
    assert "Do not claim the plan is valid" in RECOVERY_AGENT_INSTRUCTIONS
    assert "Do not invent" in RECOVERY_AGENT_INSTRUCTIONS
    assert "replanning" in RECOVERY_AGENT_INSTRUCTIONS
    assert "autonomy threshold, not a planning budget" in RECOVERY_AGENT_INSTRUCTIONS
    assert "Never leave childcare uncovered" in RECOVERY_AGENT_INSTRUCTIONS
    assert "propose it anyway" in RECOVERY_AGENT_INSTRUCTIONS
    assert "Do not create SPEND_WITHIN_AUTO_LIMIT" in RECOVERY_AGENT_INSTRUCTIONS
    assert "original conflicting time" in RECOVERY_AGENT_INSTRUCTIONS
    assert "A flat_rate is charged once" in RECOVERY_AGENT_INSTRUCTIONS
    assert "Hard feasibility always outranks" in RECOVERY_AGENT_INSTRUCTIONS
    assert "no parent segment overlaps" in RECOVERY_AGENT_INSTRUCTIONS
    assert "call each of these tools at least once" in RECOVERY_AGENT_INSTRUCTIONS
    assert "segment.start >= availability_window.available_from" in RECOVERY_AGENT_INSTRUCTIONS
    assert "segment.end <= availability_window.available_to" in RECOVERY_AGENT_INSTRUCTIONS
    assert "Never extend a caregiver segment earlier" in RECOVERY_AGENT_INSTRUCTIONS
    assert "already-selected flat-rate caregiver" in RECOVERY_AGENT_INSTRUCTIONS
    assert "coverage merely to include" in RECOVERY_AGENT_INSTRUCTIONS
    assert "coverage_required_from" in RECOVERY_AGENT_INSTRUCTIONS
    assert "starts_at and ends_at" in RECOVERY_AGENT_INSTRUCTIONS


def test_agent_proposal_defaults_to_not_validated() -> None:
    proposal = RecoveryPlan(plan_id="proposal")

    assert proposal.validation_state is PlanValidationState.NOT_VALIDATED


def test_agent_instructions_separate_context_gathering_from_structured_output() -> None:
    assert "all five context categories" in RECOVERY_AGENT_INSTRUCTIONS
    assert "Before proposing a plan" in RECOVERY_AGENT_INSTRUCTIONS


def test_tool_recorder_reports_context_tools_not_structured_output_tool() -> None:
    recorder = ToolInvocationRecorder()

    recorder(
        current_tool_use={
            "toolUseId": "context-1",
            "name": "get_family_policy",
        }
    )
    recorder(current_tool_use={"toolUseId": "output-1", "name": "RecoveryPlan"})

    assert recorder.tool_names == ["get_family_policy"]
