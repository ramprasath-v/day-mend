"""Offline contract and gateway proof for the AgentCore migration boundary."""

from io import BytesIO
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.agent.config import AgentArchitecture, RecoveryAgentConfig
from app.agent.constraint_planner import (
    PlannerOperation,
    build_planner_invocation_input,
    canonical_planner_input,
    planner_input_digest,
)
from app.agent.runtime_contracts import (
    AgentRuntimeRequest,
    AgentRuntimeResponse,
    RuntimeMetrics,
    RuntimeOperation,
    ScenarioContract,
)
from app.agent.runtime_gateway import (
    AgentCoreClient,
    AgentCoreInvocationError,
    AgentCoreRuntimeGateway,
    AgentRuntimeMode,
    runtime_mode_from_environment,
)
from app.fixtures import get_legacy_demo_scenario
from app.models import PlanValidationState, RecoveryPlan
from app.services import PlanValidator, ValidationErrorCode
from tests.milestone2_helpers import grandma_decline_event, valid_plan_b, validated_plan_a, window
from tests.test_multi_agent_architecture import active_case, initial_brief


def config() -> RecoveryAgentConfig:
    return RecoveryAgentConfig(
        model_id="offline-agentcore-model",
        region_name="us-west-2",
        architecture=AgentArchitecture.MULTI,
    )


def response(request: AgentRuntimeRequest, plan: RecoveryPlan) -> AgentRuntimeResponse:
    return AgentRuntimeResponse(
        request_id=request.request_id,
        recovery_case_id=request.recovery_case_id,
        operation=request.operation,
        success=True,
        planning_brief=request.planning_brief or initial_brief(),
        plan_candidate=plan,
        metrics=RuntimeMetrics(
            duration_ms=12,
            orchestrator_invocation_count=(
                0 if request.operation is RuntimeOperation.PLAN_REPAIR else 1
            ),
            planner_invocation_count=1,
            model_call_count=2,
            tools_used=["get_childcare_schedule"],
        ),
    )


class FakeInvoker:
    def __init__(self, plans: list[RecoveryPlan]) -> None:
        self.plans = plans.copy()
        self.requests: list[AgentRuntimeRequest] = []

    def invoke(self, request: AgentRuntimeRequest) -> AgentRuntimeResponse:
        self.requests.append(request)
        return response(request, self.plans.pop(0))


def initial_request() -> AgentRuntimeRequest:
    return AgentRuntimeRequest(
        request_id="00000000-0000-4000-8000-000000000001",
        operation=RuntimeOperation.INITIAL_PLANNING,
        architecture="multi",
        disruption="nanny unavailable",
        scenario=ScenarioContract.from_scenario(get_legacy_demo_scenario()),
    )


def test_request_and_response_round_trip_without_reasoning_fields() -> None:
    request = initial_request()
    restored = AgentRuntimeRequest.model_validate_json(request.model_dump_json())
    reply = response(request, validated_plan_a())

    assert restored == request
    assert AgentRuntimeResponse.model_validate_json(reply.model_dump_json()) == reply
    assert "chain_of_thought" not in reply.model_dump()
    assert "prompt" not in reply.model_dump()


def test_schema_version_mismatch_fails_safely() -> None:
    payload = initial_request().model_dump(mode="json")
    payload["schema_version"] = "2.0"

    with pytest.raises(ValidationError, match="unsupported AgentCore schema_version"):
        AgentRuntimeRequest.model_validate(payload)


def test_scenario_contract_preserves_request_scoped_authoritative_context() -> None:
    scenario = get_legacy_demo_scenario()

    assert ScenarioContract.from_scenario(scenario).to_scenario() == scenario


def test_agentcore_gateway_validates_remote_plan_outside_runtime() -> None:
    invoker = FakeInvoker([validated_plan_a()])
    result = AgentCoreRuntimeGateway(invoker, config()).plan_initial(
        get_legacy_demo_scenario().disruption,
        get_legacy_demo_scenario(),
    )

    assert result.success
    assert result.final_plan.validation_state is PlanValidationState.VALID
    assert invoker.requests[0].operation is RuntimeOperation.INITIAL_PLANNING


def test_remote_repair_uses_structured_feedback_and_preserves_three_attempt_cap() -> None:
    invalid = validated_plan_a().model_copy(
        update={"coverage_segments": [], "validation_state": PlanValidationState.VALID}
    )
    invoker = FakeInvoker([invalid, invalid, invalid, validated_plan_a()])
    result = AgentCoreRuntimeGateway(invoker, config()).plan_initial(
        get_legacy_demo_scenario().disruption,
        get_legacy_demo_scenario(),
    )

    assert result.success is False
    assert result.total_attempts == 3
    assert len(invoker.requests) == 3
    assert [request.operation for request in invoker.requests[1:]] == [
        RuntimeOperation.PLAN_REPAIR,
        RuntimeOperation.PLAN_REPAIR,
    ]
    assert invoker.requests[1].validator_feedback[0].code is ValidationErrorCode.COVERAGE_GAP


def test_remote_repair_preserves_exact_feedback_and_whole_plan_constraints() -> None:
    scenario = get_legacy_demo_scenario()
    invalid = validated_plan_a().model_copy(
        update={"coverage_segments": [], "validation_state": PlanValidationState.VALID}
    )
    expected_issues = PlanValidator().validate(invalid, scenario).issues
    invoker = FakeInvoker([invalid, validated_plan_a()])

    result = AgentCoreRuntimeGateway(invoker, config()).plan_initial(
        scenario.disruption,
        scenario,
    )

    repair = invoker.requests[1]
    assert repair.operation is RuntimeOperation.PLAN_REPAIR
    assert repair.validator_feedback == expected_issues
    assert repair.validator_feedback[0].code is ValidationErrorCode.COVERAGE_GAP
    assert repair.validator_feedback[0].message == (
        "Required childcare window has no coverage segments."
    )
    assert repair.scenario.to_scenario() == scenario
    assert repair.planning_brief.required_coverage_window == scenario.required_coverage
    assert repair.planning_brief == initial_brief()
    assert result.success
    assert result.total_attempts == 2
    assert result.attempts[1].validation.issues == []
    assert result.final_plan.coverage_segments[0].window.start == scenario.required_coverage.start
    assert result.final_plan.coverage_segments[-1].window.end == scenario.required_coverage.end


def test_local_and_agentcore_initial_planner_inputs_are_canonical_twins() -> None:
    scenario = get_legacy_demo_scenario()
    brief = initial_brief()
    local_input = build_planner_invocation_input(
        operation=PlannerOperation.INITIAL_PLANNING,
        brief=brief,
        scenario=scenario,
    )
    transported = AgentRuntimeRequest.model_validate_json(
        AgentRuntimeRequest(
            request_id="00000000-0000-4000-8000-000000000010",
            operation=RuntimeOperation.INITIAL_PLANNING,
            architecture="multi",
            disruption=scenario.disruption,
            scenario=ScenarioContract.from_scenario(scenario),
        ).model_dump_json()
    )
    agentcore_input = build_planner_invocation_input(
        operation=PlannerOperation(transported.operation.value),
        brief=brief,
        scenario=transported.scenario.to_scenario(),
    )

    assert canonical_planner_input(local_input) == canonical_planner_input(agentcore_input)
    assert planner_input_digest(local_input) == planner_input_digest(agentcore_input)


def test_local_and_agentcore_repair_inputs_are_canonical_and_explicit() -> None:
    scenario = get_legacy_demo_scenario()
    brief = initial_brief()
    previous = validated_plan_a().model_copy(update={"coverage_segments": []})
    issues = PlanValidator().validate(previous, scenario).issues
    local_input = build_planner_invocation_input(
        operation=PlannerOperation.PLAN_REPAIR,
        brief=brief,
        scenario=scenario,
        previous_candidate=previous,
        validator_feedback=issues,
    )
    repair_request = AgentRuntimeRequest.model_validate_json(
        AgentRuntimeRequest(
            request_id="00000000-0000-4000-8000-000000000011",
            operation=RuntimeOperation.PLAN_REPAIR,
            architecture="multi",
            scenario=ScenarioContract.from_scenario(scenario),
            planning_brief=brief,
            previous_plan=previous,
            validator_feedback=issues,
        ).model_dump_json()
    )
    agentcore_input = build_planner_invocation_input(
        operation=PlannerOperation(repair_request.operation.value),
        brief=repair_request.planning_brief,
        scenario=repair_request.scenario.to_scenario(),
        previous_candidate=repair_request.previous_plan,
        validator_feedback=repair_request.validator_feedback,
    )

    assert canonical_planner_input(local_input) == canonical_planner_input(agentcore_input)
    assert planner_input_digest(local_input) == planner_input_digest(agentcore_input)
    assert local_input.previous_candidate == previous
    assert local_input.validator_feedback == issues


def test_runtime_routing_defaults_local_and_selects_agentcore(monkeypatch) -> None:
    monkeypatch.delenv("DAYMEND_AGENT_RUNTIME", raising=False)
    assert runtime_mode_from_environment() is AgentRuntimeMode.LOCAL

    monkeypatch.setenv("DAYMEND_AGENT_RUNTIME", "agentcore")
    assert runtime_mode_from_environment() is AgentRuntimeMode.AGENTCORE


class RecordingSdkClient:
    def __init__(self, reply: AgentRuntimeResponse | None = None, error=None) -> None:
        self.reply = reply
        self.error = error
        self.kwargs = None

    def invoke_agent_runtime(self, **kwargs):
        self.kwargs = kwargs
        if self.error is not None:
            raise self.error
        return {"response": BytesIO(self.reply.model_dump_json().encode())}


def test_agentcore_client_uses_iam_sdk_path_and_includes_request_id() -> None:
    request = initial_request()
    sdk = RecordingSdkClient(response(request, validated_plan_a()))
    client = AgentCoreClient("arn:aws:bedrock-agentcore:us-west-2:123:runtime/daymend", client=sdk)

    assert client.invoke(request).request_id == request.request_id
    assert sdk.kwargs["runtimeSessionId"] == request.request_id
    assert request.request_id.encode() in sdk.kwargs["payload"]
    assert "credentials" not in sdk.kwargs


def test_agentcore_transport_failure_maps_to_safe_error() -> None:
    sdk = RecordingSdkClient(error=ValueError("wire detail"))
    client = AgentCoreClient("runtime-arn", client=sdk)

    with pytest.raises(AgentCoreInvocationError, match="failed safely"):
        client.invoke(initial_request())


def test_replanning_invalidation_is_application_side() -> None:
    invalidation = SimpleNamespace(calls=0)

    def apply(case, event, scenario):
        invalidation.calls += 1
        raise ValueError("proof before transport")

    invalidation.apply_caregiver_decline = apply
    gateway = AgentCoreRuntimeGateway(
        FakeInvoker([valid_plan_b()]), config(), invalidation_service=invalidation
    )

    with pytest.raises(ValueError, match="proof before transport"):
        gateway.replan(SimpleNamespace(), SimpleNamespace(), get_legacy_demo_scenario())
    assert invalidation.calls == 1


def test_remote_plan_b_preserves_application_owned_plan_a_history() -> None:
    gateway = AgentCoreRuntimeGateway(FakeInvoker([valid_plan_b()]), config())

    result = gateway.replan(active_case(), grandma_decline_event(), get_legacy_demo_scenario())

    assert result.success
    assert result.final_plan.plan_id == "plan-b"
    assert result.recovery_case.active_recovery_plan.plan_id == "plan-b"
    assert [plan.plan_id for plan in result.recovery_case.previous_plans] == ["plan-a"]


def test_agentcore_failure_does_not_mutate_authoritative_case() -> None:
    original = active_case()

    class RaisingInvoker:
        def invoke(self, request):
            raise AgentCoreInvocationError("unavailable")

    with pytest.raises(AgentCoreInvocationError):
        AgentCoreRuntimeGateway(RaisingInvoker(), config()).replan(
            original,
            grandma_decline_event(),
            get_legacy_demo_scenario(),
        )
    assert original.active_recovery_plan.plan_id == "plan-a"
    assert original.previous_plans == []


def test_contract_rejects_repair_without_authoritative_feedback() -> None:
    with pytest.raises(ValidationError, match="PLAN_REPAIR requires"):
        AgentRuntimeRequest(
            request_id="00000000-0000-4000-8000-000000000002",
            operation=RuntimeOperation.PLAN_REPAIR,
            architecture="multi",
            scenario=ScenarioContract.from_scenario(get_legacy_demo_scenario()),
            planning_brief=initial_brief(),
            previous_plan=validated_plan_a(),
        )


def test_contract_contains_no_lifecycle_authority() -> None:
    fields = AgentRuntimeResponse.model_fields

    assert "recovery_case" not in fields
    assert "approval" not in fields
    assert "status" not in fields
    assert "resolved" not in fields
    assert window(8, 16) == initial_brief().required_coverage_window
