"""Local and AgentCore implementations of the application reasoning boundary."""

import os
from enum import StrEnum
from time import perf_counter
from typing import Any, Protocol
from uuid import uuid4

import boto3
from botocore.config import Config
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    ConnectionClosedError,
    ConnectTimeoutError,
    EndpointConnectionError,
)

from app.agent.config import RecoveryAgentConfig
from app.agent.recovery_agent import (
    MAX_PLAN_ATTEMPTS,
    InitialPlanningResult,
    PlanningAttempt,
)
from app.agent.replanning import ReplanningResult, build_replanning_result
from app.agent.runtime_contracts import (
    AgentRuntimeRequest,
    AgentRuntimeResponse,
    ReplanningContext,
    RuntimeOperation,
    ScenarioContract,
)
from app.fixtures import DemoScenario
from app.models import RecoveryCase, RecoveryEvent, RecoveryPlanSegment
from app.observability import log_event
from app.services import PlanInvalidationService, PlanValidator, add_researched_caregiver


class AgentRuntimeMode(StrEnum):
    LOCAL = "local"
    AGENTCORE = "agentcore"


class AgentCoreInvocationError(RuntimeError):
    """Safe transport failure that exposes no SDK payload or credentials."""


_RETRYABLE_AGENTCORE_TRANSPORT_ERRORS = (
    ConnectionClosedError,
    ConnectTimeoutError,
    EndpointConnectionError,
)


class RuntimeInvoker(Protocol):
    def invoke(self, request: AgentRuntimeRequest) -> AgentRuntimeResponse: ...


class AgentCoreClient:
    """IAM-authenticated AgentCore data-plane client with no ambiguous retries."""

    def __init__(
        self,
        runtime_arn: str,
        *,
        region_name: str | None = None,
        read_timeout_seconds: int = 110,
        client: Any | None = None,
    ) -> None:
        self.runtime_arn = runtime_arn
        self._client = client or boto3.client(
            "bedrock-agentcore",
            region_name=region_name,
            config=Config(
                connect_timeout=10,
                read_timeout=read_timeout_seconds,
                retries={"total_max_attempts": 1, "mode": "standard"},
            ),
        )

    def invoke(self, request: AgentRuntimeRequest) -> AgentRuntimeResponse:
        started = perf_counter()
        request_payload = request.model_dump_json().encode()
        log_event(
            "agentcore_invocation_started",
            request_id=request.request_id,
            recovery_case_id=request.recovery_case_id,
            operation=request.operation,
        )
        for transport_attempt in range(2):
            try:
                raw = self._client.invoke_agent_runtime(
                    agentRuntimeArn=self.runtime_arn,
                    runtimeSessionId=request.request_id,
                    payload=request_payload,
                )
                body = raw["response"]
                response_payload = body.read() if hasattr(body, "read") else body
                if isinstance(response_payload, bytes):
                    response_payload = response_payload.decode("utf-8")
                response = AgentRuntimeResponse.model_validate_json(response_payload)
                if response.request_id != request.request_id:
                    raise AgentCoreInvocationError("AgentCore response request_id did not match")
                break
            except AgentCoreInvocationError:
                raise
            except _RETRYABLE_AGENTCORE_TRANSPORT_ERRORS as exc:
                if transport_attempt == 0:
                    log_event(
                        "agentcore_transport_retry",
                        request_id=request.request_id,
                        recovery_case_id=request.recovery_case_id,
                        operation=request.operation,
                        retry_number=1,
                        error_type=type(exc).__name__,
                    )
                    continue
                self._log_failure(request, started, exc)
                raise AgentCoreInvocationError(
                    "AgentCore reasoning invocation failed safely"
                ) from exc
            except (BotoCoreError, ClientError, KeyError, TypeError, ValueError) as exc:
                self._log_failure(request, started, exc)
                raise AgentCoreInvocationError(
                    "AgentCore reasoning invocation failed safely"
                ) from exc
        log_event(
            "agentcore_invocation_completed",
            request_id=request.request_id,
            recovery_case_id=request.recovery_case_id,
            operation=request.operation,
            duration_ms=round((perf_counter() - started) * 1000),
            response_status="success",
            orchestrator_invocation_count=response.metrics.orchestrator_invocation_count,
            research_agent_invocation_count=response.metrics.research_agent_invocation_count,
            planner_invocation_count=response.metrics.planner_invocation_count,
            model_call_count=response.metrics.model_call_count,
        )
        return response

    @staticmethod
    def _log_failure(
        request: AgentRuntimeRequest,
        started: float,
        exc: Exception,
    ) -> None:
        log_event(
            "agentcore_invocation_failed",
            request_id=request.request_id,
            recovery_case_id=request.recovery_case_id,
            operation=request.operation,
            duration_ms=round((perf_counter() - started) * 1000),
            error_type=type(exc).__name__,
        )


class AgentCoreRuntimeGateway:
    """Application-side validation and repair loop over stateless AgentCore proposals."""

    def __init__(
        self,
        invoker: RuntimeInvoker,
        config: RecoveryAgentConfig | None = None,
        *,
        validator: PlanValidator | None = None,
        invalidation_service: PlanInvalidationService | None = None,
    ) -> None:
        self._invoker = invoker
        self._config = config or RecoveryAgentConfig.from_environment()
        self._validator = validator or PlanValidator()
        self._invalidation = invalidation_service or PlanInvalidationService()

    def plan_initial(self, disruption: str, scenario: DemoScenario) -> InitialPlanningResult:
        response = self._invoker.invoke(
            self._request(
                RuntimeOperation.INITIAL_PLANNING,
                scenario,
                disruption=disruption,
            )
        )
        self._log_research_response(response)
        planning_scenario = scenario
        if response.researched_candidate is not None:
            planning_scenario = add_researched_caregiver(scenario, response.researched_candidate)
        attempts, responses = self._validate_with_repairs(
            response,
            scenario=scenario,
            validation_scenario=planning_scenario,
        )
        final = attempts[-1].validation
        metrics = self._aggregate(responses)
        return InitialPlanningResult(
            success=final.valid,
            total_attempts=len(attempts),
            model_id=self._config.model_id,
            tools_used=metrics["tools_used"],
            attempts=attempts,
            final_plan=final.validated_plan if final.valid else None,
            deterministic_total_cost=final.deterministic_total_cost,
            requires_approval=final.requires_approval,
            final_errors=[] if final.valid else final.issues,
            architecture=self._config.architecture.value,
            orchestrator_invocation_count=metrics["orchestrator"],
            research_agent_invocation_count=metrics["research"],
            planner_invocation_count=metrics["planner"],
            model_call_count=metrics["model_calls"],
            tool_call_count=len(metrics["tools_used"]),
            researched_candidate=response.researched_candidate,
        )

    def replan(
        self,
        recovery_case: RecoveryCase,
        event: RecoveryEvent,
        scenario: DemoScenario,
    ) -> ReplanningResult:
        outcome = self._invalidation.apply_caregiver_decline(recovery_case, event, scenario)
        context = ReplanningContext(
            recovery_case=outcome.recovery_case,
            previous_status=outcome.previous_status,
            original_valid_plan=outcome.original_valid_plan,
            invalidated_assumptions=list(outcome.invalidated_assumptions),
            impacted_segments=list(outcome.impacted_segments),
            impact_reasons=list(outcome.impact_reasons),
            preserved_segments=list(outcome.preserved_segments),
            uncovered_windows=list(outcome.uncovered_windows),
        )
        response = self._invoker.invoke(
            self._request(
                RuntimeOperation.REPLANNING,
                outcome.updated_scenario,
                recovery_case_id=recovery_case.case_id,
                replanning_context=context,
            )
        )
        self._log_research_response(response)
        validation_scenario = outcome.updated_scenario
        if response.researched_candidate is not None:
            validation_scenario = add_researched_caregiver(
                outcome.updated_scenario, response.researched_candidate
            )
        attempts, responses = self._validate_with_repairs(
            response,
            scenario=outcome.updated_scenario,
            validation_scenario=validation_scenario,
            recovery_case_id=recovery_case.case_id,
            preserved_segments=list(outcome.preserved_segments),
        )
        metrics = self._aggregate(responses)
        return build_replanning_result(
            outcome=outcome,
            event=event,
            attempts=attempts,
            tools_used=metrics["tools_used"],
            architecture=self._config.architecture.value,
            orchestrator_invocation_count=metrics["orchestrator"],
            planner_invocation_count=metrics["planner"],
            model_call_count=metrics["model_calls"],
            research_agent_invocation_count=metrics["research"],
            researched_candidate=response.researched_candidate,
        )

    def _validate_with_repairs(
        self,
        first: AgentRuntimeResponse,
        *,
        scenario: DemoScenario,
        validation_scenario: DemoScenario,
        recovery_case_id: str | None = None,
        preserved_segments: list[RecoveryPlanSegment] | None = None,
    ) -> tuple[list[PlanningAttempt], list[AgentRuntimeResponse]]:
        responses = [first]
        attempts: list[PlanningAttempt] = []
        current = first
        for attempt_number in range(1, MAX_PLAN_ATTEMPTS + 1):
            phase = (
                "initial_planning"
                if first.operation is RuntimeOperation.INITIAL_PLANNING
                else "replanning"
            )
            attempt_fields = {
                "architecture": self._config.architecture.value,
                "agent_role": "constraint_planner",
                "planning_mode": phase,
                "recovery_case_id": recovery_case_id,
                "model_id": self._config.model_id,
                "operation": current.operation,
                "attempt_number": attempt_number,
                "plan_id": current.plan_candidate.plan_id,
            }
            log_event("plan_proposed", **attempt_fields)
            log_event("validation_started", **attempt_fields)
            validation = (
                self._validator.validate_repair(
                    current.plan_candidate,
                    validation_scenario,
                    preserved_segments or [],
                )
                if preserved_segments
                else self._validator.validate(current.plan_candidate, validation_scenario)
            )
            validation_fields = {
                **attempt_fields,
                "valid": validation.valid,
                "issue_count": len(validation.issues),
                "issue_codes": [issue.code for issue in validation.issues],
            }
            log_event(
                "planner_validation_succeeded" if validation.valid else "planner_validation_failed",
                **validation_fields,
            )
            attempts.append(
                PlanningAttempt(
                    attempt_number=attempt_number,
                    proposed_plan=current.plan_candidate,
                    validation=validation,
                    model_call_count=current.metrics.model_call_count,
                )
            )
            if validation.valid or attempt_number == MAX_PLAN_ATTEMPTS:
                break
            log_event(
                "plan_repair_started",
                **{
                    **validation_fields,
                    "operation": RuntimeOperation.PLAN_REPAIR,
                    "attempt_number": attempt_number + 1,
                },
            )
            current = self._invoker.invoke(
                self._request(
                    RuntimeOperation.PLAN_REPAIR,
                    scenario,
                    recovery_case_id=recovery_case_id,
                    planning_brief=first.planning_brief,
                    previous_plan=current.plan_candidate,
                    validator_feedback=validation.issues,
                    researched_candidate=first.researched_candidate,
                )
            )
            responses.append(current)
        return attempts, responses

    @staticmethod
    def _log_research_response(response: AgentRuntimeResponse) -> None:
        research = response.backup_care_research
        if research is None:
            return
        fields = {
            "architecture": "multi_research",
            "agent_role": "backup_care_researcher",
            "planning_mode": (
                "initial"
                if response.operation is RuntimeOperation.INITIAL_PLANNING
                else "replanning"
            ),
            "recovery_case_id": response.recovery_case_id,
            "candidate_count": len(research.considered_candidate_ids),
            "eligible_candidate_count": len(research.eligible_candidate_ids),
        }
        log_event("known_options_exhausted", **fields)
        log_event("backup_research_started", **fields)
        log_event("backup_candidates_received", **fields)
        log_event(
            "backup_candidate_recommended",
            **fields,
            research_id=research.research_id,
            recommended_candidate_id=(
                response.researched_candidate.candidate_id
                if response.researched_candidate is not None
                else research.recommended_candidate_id
            ),
        )

    def _request(
        self,
        operation: RuntimeOperation,
        scenario: DemoScenario,
        **updates: Any,
    ) -> AgentRuntimeRequest:
        return AgentRuntimeRequest(
            request_id=str(uuid4()),
            operation=operation,
            architecture=self._config.architecture.value,
            scenario=ScenarioContract.from_scenario(scenario),
            **updates,
        )

    @staticmethod
    def _aggregate(responses: list[AgentRuntimeResponse]) -> dict[str, Any]:
        return {
            "orchestrator": sum(r.metrics.orchestrator_invocation_count for r in responses),
            "research": sum(r.metrics.research_agent_invocation_count for r in responses),
            "planner": sum(r.metrics.planner_invocation_count for r in responses),
            "model_calls": sum(r.metrics.model_call_count for r in responses),
            "tools_used": [tool for r in responses for tool in r.metrics.tools_used],
        }


def runtime_mode_from_environment() -> AgentRuntimeMode:
    raw = os.getenv("DAYMEND_AGENT_RUNTIME", AgentRuntimeMode.LOCAL).strip().lower()
    try:
        return AgentRuntimeMode(raw)
    except ValueError as exc:
        raise ValueError("DAYMEND_AGENT_RUNTIME must be 'local' or 'agentcore'") from exc


def build_agentcore_gateway() -> AgentCoreRuntimeGateway:
    runtime_arn = os.getenv("DAYMEND_AGENTCORE_RUNTIME_ARN", "").strip()
    if not runtime_arn:
        raise ValueError("DAYMEND_AGENTCORE_RUNTIME_ARN is required for agentcore runtime")
    config = RecoveryAgentConfig.from_environment()
    timeout = int(os.getenv("DAYMEND_AGENTCORE_READ_TIMEOUT_SECONDS", "110"))
    return AgentCoreRuntimeGateway(
        AgentCoreClient(
            runtime_arn,
            region_name=config.region_name,
            read_timeout_seconds=timeout,
        ),
        config,
    )
