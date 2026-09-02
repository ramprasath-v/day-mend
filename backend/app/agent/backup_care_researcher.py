"""Grounded multi-candidate reasoning for synthetic backup-care research."""

import json
from time import perf_counter
from typing import Any, Protocol

from pydantic import Field, model_validator
from strands import Agent
from strands.models import BedrockModel

from app.agent.config import RecoveryAgentConfig
from app.agent.recovery_agent import ToolInvocationRecorder, model_call_count
from app.fixtures import DemoScenario
from app.models import BackupCareCandidate, ContractModel, CoverageWindow
from app.services import BackupCareSearchResult, RecoveryNeed, search_backup_care_candidates
from app.tools import BACKUP_CARE_RESEARCH_TOOLS, use_backup_care_request, use_scenario


class RankedBackupCareCandidate(ContractModel):
    """One eligible candidate's model-generated comparative ranking explanation."""

    candidate_id: str
    rank: int = Field(ge=1)
    fit_summary: str = Field(min_length=1, max_length=400)
    tradeoffs: list[str] = Field(default_factory=list, min_length=1, max_length=5)


class BackupCareResearchResult(ContractModel):
    """Structured recommendation contract without validity or approval authority."""

    research_id: str
    requested_windows: list[CoverageWindow]
    considered_candidate_ids: list[str] = Field(default_factory=list)
    eligible_candidate_ids: list[str] = Field(default_factory=list)
    ranked_candidates: list[RankedBackupCareCandidate] = Field(default_factory=list)
    recommended_candidate_id: str | None = None
    unresolved_windows: list[CoverageWindow] = Field(default_factory=list)

    @model_validator(mode="after")
    def ranks_are_unique(self) -> "BackupCareResearchResult":
        ranks = [candidate.rank for candidate in self.ranked_candidates]
        if len(ranks) != len(set(ranks)):
            raise ValueError("backup-care candidate ranks must be unique")
        return self


class BackupCareResearchRun(ContractModel):
    """Safe orchestration diagnostics for one optional specialist invocation."""

    result: BackupCareResearchResult
    search_result: BackupCareSearchResult
    recommended_candidate: BackupCareCandidate
    model_call_count: int = Field(default=0, ge=0)
    tool_call_count: int = Field(default=0, ge=0)
    tools_used: list[str] = Field(default_factory=list)
    duration_ms: int = Field(default=0, ge=0)


class BackupCareResearcherLike(Protocol):
    """Structured invocation surface shared by Strands and offline fakes."""

    def __call__(
        self,
        prompt: str,
        *,
        structured_output_model: type[BackupCareResearchResult] | None = None,
    ) -> Any: ...


BACKUP_CARE_RESEARCH_INSTRUCTIONS = """
You are DayMend's Backup Care Research Agent. You are invoked only after authoritative interval
analysis shows that the family's known options cannot fully cover required childcare. Call
search_backup_care exactly once. That tool uses synthetic provider inventory and has already
applied hard availability, verification, background-check, and child-age rules.

Compare every eligible candidate using the family's soft preferences and meaningful tradeoffs:
price, distance, rating, review history, prior use, and fit for the requested windows. Rank every
eligible candidate, recommend one grounded candidate ID, and explain concise tradeoffs. Never
invent a candidate or include a hard-ineligible candidate in the ranking.

You do not construct or validate a RecoveryPlan, calculate authoritative final plan cost, decide
whether approval is required, book care, persist state, execute actions, or mark recovery
complete. Do not expose chain-of-thought. Return only BackupCareResearchResult.
""".strip()


def build_backup_care_researcher(
    config: RecoveryAgentConfig,
    recorder: ToolInvocationRecorder,
) -> Agent:
    """Create the third and final Strands reasoning agent with research-only tools."""

    model = BedrockModel(
        model_id=config.model_id,
        region_name=config.region_name,
        temperature=0.0,
        max_tokens=3072,
    )
    return Agent(
        name="daymend_backup_care_researcher",
        description="Compares grounded backup-care candidates for unresolved childcare windows.",
        model=model,
        tools=BACKUP_CARE_RESEARCH_TOOLS,
        system_prompt=BACKUP_CARE_RESEARCH_INSTRUCTIONS,
        callback_handler=recorder,
    )


def run_backup_care_research(
    *,
    researcher: BackupCareResearcherLike,
    recorder: ToolInvocationRecorder,
    scenario: DemoScenario,
    recovery_need: RecoveryNeed,
) -> BackupCareResearchRun:
    """Invoke research once, then reject any recommendation not grounded in tool output."""

    if not recovery_need.research_needed or not recovery_need.requested_windows:
        raise ValueError("backup-care research requires an unresolved known-options window")
    grounding = search_backup_care_candidates(scenario, recovery_need.requested_windows)
    eligible_ids = [candidate.candidate_id for candidate in grounding.eligible_candidates]
    if len(eligible_ids) < 2:
        raise RuntimeError("backup-care research requires multiple eligible candidates to compare")

    started = perf_counter()
    tools_before = len(recorder.tool_names)
    context = {
        "requested_windows": [
            window.model_dump(mode="json") for window in recovery_need.requested_windows
        ],
        "child_age_years": scenario.child_age_years,
        "family_preferences": scenario.preferences.model_dump(mode="json"),
        "hard_family_policy": scenario.policy.model_dump(mode="json"),
        "already_considered_known_caregiver_ids": (recovery_need.already_considered_caregiver_ids),
    }
    with use_scenario(scenario), use_backup_care_request(recovery_need.requested_windows):
        response = researcher(
            "Research compatible backup care for this authoritative unresolved need. Call the "
            "research tool, compare every eligible result, and return a grounded ranking. "
            f"Research context: {json.dumps(context, separators=(',', ':'), default=str)}",
            structured_output_model=BackupCareResearchResult,
        )
    if response.structured_output is None:
        raise RuntimeError("Strands Backup Care Research Agent returned no structured result")
    tools_used = recorder.tool_names[tools_before:]
    if tools_used != ["search_backup_care"]:
        raise RuntimeError("Backup Care Research Agent must call search_backup_care exactly once")

    proposed = response.structured_output
    ranked_ids = [candidate.candidate_id for candidate in proposed.ranked_candidates]
    if set(ranked_ids) != set(eligible_ids) or len(ranked_ids) != len(eligible_ids):
        raise RuntimeError("Backup Care Research Agent ranking was not grounded to eligible IDs")
    if proposed.recommended_candidate_id not in eligible_ids:
        raise RuntimeError("Backup Care Research Agent recommended an ineligible candidate ID")
    normalized = proposed.model_copy(
        update={
            "research_id": _research_id(recovery_need.requested_windows),
            "requested_windows": recovery_need.requested_windows,
            "considered_candidate_ids": [
                assessment.candidate.candidate_id for assessment in grounding.considered_candidates
            ],
            "eligible_candidate_ids": eligible_ids,
            "unresolved_windows": [],
        }
    )
    candidates = {candidate.candidate_id: candidate for candidate in grounding.eligible_candidates}
    return BackupCareResearchRun(
        result=normalized,
        search_result=grounding,
        recommended_candidate=candidates[normalized.recommended_candidate_id],
        model_call_count=model_call_count(response),
        tool_call_count=len(tools_used),
        tools_used=tools_used,
        duration_ms=round((perf_counter() - started) * 1000),
    )


def _research_id(windows: list[CoverageWindow]) -> str:
    boundaries = ":".join(
        f"{window.start.isoformat()}-{window.end.isoformat()}" for window in windows
    )
    return f"backup-care-research:{boundaries}"
