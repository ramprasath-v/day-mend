"""Thin application coordinator over the proven recovery domain and services."""

from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol
from uuid import uuid4

from app.agent.config import RecoveryAgentConfig
from app.agent.recovery_agent import (
    InitialPlanningResult,
    ToolInvocationRecorder,
    build_recovery_agent,
    run_initial_planning_session,
)
from app.agent.replanning import ReplanningResult, process_external_event
from app.fixtures import DemoScenario, get_demo_scenario
from app.models import (
    CoverageWindow,
    RecoveryCase,
    RecoveryEvent,
    RecoveryEventType,
    RecoveryStatus,
)
from app.repositories import RecoveryCaseRepository
from app.services import (
    ApprovalService,
    CompletionVerifier,
    RecoveryExecutionService,
    WorkflowInvariantError,
    apply_caregiver_decline_to_scenario,
    create_active_recovery_case,
)


class ApplicationError(RuntimeError):
    """Safe application-layer failure that may be mapped to an HTTP error."""

    code = "INVALID_RECOVERY_STATE"


class ApplicationConflict(ApplicationError):
    """A caller attempted to mutate a stale aggregate version."""

    code = "PERSISTENCE_CONFLICT"


class EventNotApplicable(ApplicationError):
    """An external event does not affect the active plan."""

    code = "EVENT_NOT_APPLICABLE"


class PlanningFailed(ApplicationError):
    """The bounded initial-planning workflow produced no valid plan."""

    code = "PLANNING_FAILED"


class ReplanningFailed(ApplicationError):
    """The bounded world-state replanning workflow produced no valid plan."""

    code = "REPLANNING_FAILED"


class ApprovalDecision(StrEnum):
    """Human decision accepted by the application boundary."""

    APPROVE = "APPROVE"
    REJECT = "REJECT"


class StartRecoveryCommand:
    """Provider-neutral command used to begin a recovery."""

    def __init__(
        self,
        *,
        disruption_type: str,
        occurred_at: datetime,
        caregiver_id: str,
        message: str,
    ) -> None:
        self.disruption_type = disruption_type
        self.occurred_at = occurred_at
        self.caregiver_id = caregiver_id
        self.message = message


class EventCommand:
    """Provider-neutral external event command."""

    def __init__(
        self,
        *,
        event_type: RecoveryEventType,
        caregiver_id: str,
        occurred_at: datetime,
        relevant_window: CoverageWindow,
        message: str,
        event_id: str | None = None,
        expected_version: int | None = None,
    ) -> None:
        self.event_type = event_type
        self.caregiver_id = caregiver_id
        self.occurred_at = occurred_at
        self.relevant_window = relevant_window
        self.message = message
        self.event_id = event_id
        self.expected_version = expected_version


class ApprovalCommand:
    """Provider-neutral approval command."""

    def __init__(
        self,
        *,
        decision: ApprovalDecision,
        reason: str | None = None,
        expected_version: int | None = None,
    ) -> None:
        self.decision = decision
        self.reason = reason
        self.expected_version = expected_version


class RecoveryPlanningGateway(Protocol):
    """Narrow model boundary used by application orchestration and offline fakes."""

    def plan_initial(self, disruption: str, scenario: DemoScenario) -> InitialPlanningResult: ...

    def replan(
        self,
        recovery_case: RecoveryCase,
        event: RecoveryEvent,
        scenario: DemoScenario,
    ) -> ReplanningResult: ...


class StrandsRecoveryPlanningGateway:
    """Real gateway to the single configured Strands Recovery Agent responsibility."""

    def __init__(self, config: RecoveryAgentConfig | None = None) -> None:
        self._config = config or RecoveryAgentConfig.from_environment()

    def plan_initial(self, disruption: str, scenario: DemoScenario) -> InitialPlanningResult:
        recorder = ToolInvocationRecorder()
        agent = build_recovery_agent(self._config, recorder)
        return run_initial_planning_session(
            agent=agent,
            recorder=recorder,
            disruption=disruption,
            scenario=scenario,
            model_id=self._config.model_id,
        )

    def replan(
        self,
        recovery_case: RecoveryCase,
        event: RecoveryEvent,
        scenario: DemoScenario,
    ) -> ReplanningResult:
        recorder = ToolInvocationRecorder()
        agent = build_recovery_agent(self._config, recorder)
        return process_external_event(
            recovery_case=recovery_case,
            event=event,
            scenario=scenario,
            agent=agent,
            recorder=recorder,
        )


class RecoveryApplicationService:
    """Coordinate planning, persistence, event handling, approval, and completion."""

    def __init__(
        self,
        repository: RecoveryCaseRepository,
        planning_gateway: RecoveryPlanningGateway,
        *,
        scenario_factory: Callable[[], DemoScenario] = get_demo_scenario,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.repository = repository
        self._planning = planning_gateway
        self._scenario_factory = scenario_factory
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_factory = id_factory or (lambda: str(uuid4()))
        self._approval = ApprovalService(repository)
        self._execution = RecoveryExecutionService(repository)
        self._completion = CompletionVerifier(repository)

    def start_recovery(self, command: StartRecoveryCommand) -> RecoveryCase:
        scenario = self._scenario_factory()
        disruption = f"{command.disruption_type}: {command.message}"
        planning = self._planning.plan_initial(disruption, scenario)
        if not planning.success or planning.final_plan is None:
            raise PlanningFailed("DayMend could not produce a valid initial recovery plan.")

        now = self._clock()
        case_id = self._id_factory()
        disruption_event = RecoveryEvent(
            event_id=f"disruption:{case_id}",
            event_type=RecoveryEventType.DISRUPTION_DETECTED,
            occurred_at=command.occurred_at,
            caregiver_id=command.caregiver_id,
            message=command.message,
            details={"disruption_type": command.disruption_type},
        )
        recovery_case = create_active_recovery_case(
            case_id=case_id,
            disruption=disruption,
            validated_plan=planning.final_plan,
            required_coverage=scenario.required_coverage,
            now=now,
        ).model_copy(
            update={
                "events": [disruption_event],
                "context_state": {
                    "original_disruption": {
                        "disruption_type": command.disruption_type,
                        "occurred_at": command.occurred_at.isoformat(),
                        "caregiver_id": command.caregiver_id,
                        "message": command.message,
                    }
                },
                "family_policy": scenario.policy,
            }
        )
        return self.repository.save(recovery_case)

    def get_recovery(self, case_id: str) -> RecoveryCase:
        return self.repository.get(case_id)

    def process_event(self, case_id: str, command: EventCommand) -> RecoveryCase:
        recovery_case = self.repository.get(case_id)
        self._check_expected_version(recovery_case, command.expected_version)
        if command.event_type is not RecoveryEventType.CAREGIVER_DECLINED:
            raise EventNotApplicable(f"Event type {command.event_type} is not supported.")

        scenario = self._scenario_for(recovery_case)
        event = RecoveryEvent(
            event_id=command.event_id or f"event:{self._id_factory()}",
            event_type=command.event_type,
            caregiver_id=command.caregiver_id,
            relevant_window=command.relevant_window,
            occurred_at=command.occurred_at,
            message=command.message,
        )
        try:
            result = self._planning.replan(recovery_case, event, scenario)
        except ValueError as exc:
            raise EventNotApplicable(str(exc)) from exc

        replanned = self.repository.save(
            result.recovery_case,
            expected_version=recovery_case.version,
        )
        if not result.success:
            raise ReplanningFailed("DayMend could not produce a valid replacement plan.")

        gate = self._approval.apply_autonomy_gate(
            replanned,
            result.final_validation,
            self._scenario_for(replanned).policy,
            now=self._now(replanned.updated_at),
        )
        if gate.approval_required:
            return gate.recovery_case
        return self._execute_and_complete(gate.recovery_case.case_id)

    def decide_approval(
        self,
        case_id: str,
        approval_id: str,
        command: ApprovalCommand,
    ) -> RecoveryCase:
        current = self.repository.get(case_id)
        self._check_expected_version(current, command.expected_version)
        try:
            if command.decision is ApprovalDecision.APPROVE:
                result = self._approval.approve(
                    case_id,
                    approval_id,
                    now=self._now(current.updated_at),
                )
            else:
                result = self._approval.reject(
                    case_id,
                    approval_id,
                    now=self._now(current.updated_at),
                    reason=command.reason,
                )
        except WorkflowInvariantError:
            raise

        if command.decision is ApprovalDecision.REJECT:
            return result.recovery_case
        if result.idempotent and result.recovery_case.status is RecoveryStatus.RESOLVED:
            return result.recovery_case
        return self._execute_and_complete(case_id)

    def _execute_and_complete(self, case_id: str) -> RecoveryCase:
        current = self.repository.get(case_id)
        scenario = self._scenario_for(current)
        execution = self._execution.execute(
            case_id,
            scenario.policy,
            now=self._now(current.updated_at),
        )
        if not execution.succeeded:
            return execution.recovery_case
        completion = self._completion.verify_and_resolve(
            case_id,
            scenario,
            now=self._now(execution.recovery_case.updated_at),
        )
        return completion.recovery_case

    def _scenario_for(self, recovery_case: RecoveryCase) -> DemoScenario:
        scenario = self._scenario_factory()
        for event in recovery_case.events:
            if event.event_type is RecoveryEventType.CAREGIVER_DECLINED:
                scenario = apply_caregiver_decline_to_scenario(scenario, event)
        return scenario

    def _now(self, not_before: datetime) -> datetime:
        """Keep aggregate timestamps monotonic when external event clocks differ."""

        return max(self._clock(), not_before)

    @staticmethod
    def _check_expected_version(
        recovery_case: RecoveryCase,
        expected_version: int | None,
    ) -> None:
        if expected_version is not None and expected_version != recovery_case.version:
            raise ApplicationConflict(
                f"Expected recovery version {expected_version}, found {recovery_case.version}."
            )
