# DayMend Architecture

## System boundary

DayMend is a childcare disruption recovery agent. Its central unit of work is a persistent
`RecoveryCase`, not a chat session or a one-shot babysitter search. The case retains the facts,
plans, assumptions, decisions, external outcomes, and status needed to recover safely across
pauses and replanning cycles.

## Recovery flow

```text
Disruption / external event
        ↓
Recovery Case
        ↓
Strands Recovery Agent
        ↓
Context/tool gathering
        ↓
Recovery strategy
        ↓
Structured RecoveryPlan
        ↓
Deterministic Validator
        ↓
Execution
        ↓
Observe external outcome
        ↓
Either: continue | replan | request approval
        ↓
Resume if necessary
        ↓
Completion verification
        ↓
RESOLVED
```

The agent may propose a strategy and structured plan, but a deterministic validator decides
whether that plan satisfies hard constraints. Execution outcomes update the case's world state.
If an assumption becomes false, the system recalculates the remaining coverage gap and asks the
agent to repair the plan from current facts rather than following a prewritten branch.

Approval is a persisted state transition. When the parent decides, the same case resumes with
that decision recorded. Final deterministic verification is the only path to `RESOLVED`.

## Responsibility boundary

Agent/LLM reasoning is appropriate for:

- interpreting a natural-language disruption;
- deciding which context and tools are needed;
- balancing hard constraints and soft family preferences;
- proposing a recovery strategy and structured plan;
- deciding which portion of a plan needs repair after a change; and
- selecting the next action from valid options.

Deterministic code must enforce:

- complete childcare coverage;
- trusted or explicitly approved caregivers;
- caregiver availability and non-overlapping assignments;
- feasible handoffs and travel;
- spending thresholds and approval requirements; and
- final action and coverage verification.

## Future tool categories

The Recovery Agent may eventually use tools for:

- childcare schedules;
- parent calendars;
- trusted caregivers;
- caregiver availability;
- caregiver communication and responses;
- family policy;
- backup-care availability;
- calendar actions;
- approval;
- booking and action execution; and
- final coverage verification.

Tools are not separate agents by default. They expose data or deterministic actions to the one
core Recovery Agent. Multi-agent specialization is justified only if future implementation
reveals genuinely separate, durable reasoning responsibilities.

## Milestone 1 implementation

Milestone 1 uses exactly one Strands `Agent`, backed by `BedrockModel`. The agent receives the
disruption rather than a preassembled context bundle and chooses among five read-only `@tool`
capabilities:

- `get_childcare_schedule`
- `get_parent_calendars`
- `get_caregivers`
- `get_family_preferences`
- `get_family_policy`

The agent returns a typed `RecoveryPlan` through Strands structured output. Application code
forcibly resets its state to `NOT_VALIDATED`; the model cannot certify its own proposal.

`PlanValidator` then independently reads the authoritative synthetic scenario and checks full
coverage, gaps, supported identities, caregiver trust and availability, parent calendar
conflicts, handoff feasibility, costs, and hard policy. It returns a validated plan copy with
deterministically recomputed segment and total costs.

Initial planning uses a bounded proposal/validation/repair loop. The five tools gather context
once in a single Strands agent conversation. If validation fails, the validator's structured
issues—stable code, message, and relevant subject/segment/event identifiers—are sent back to the
same agent. The unchanged context is reused and the agent returns a complete repaired proposal.
The loop stops immediately on success or after `MAX_PLAN_ATTEMPTS = 3`; after three invalid
proposals it returns a structured failure with no accepted plan. Application code never inserts
a fallback plan, and the agent cannot waive an issue.

This is initial-plan repair: Plan A has never been valid and the authoritative world state has
not changed. It is distinct from Milestone 2 replanning, where an external event invalidates a
previously valid or executing plan. No external-event invalidation behavior is implemented here.

`FamilyPreferences` are soft. The validator may warn that a proposal did not follow them but
does not reject an otherwise allowed plan. `FamilyPolicy` is hard. `Caregiver.is_trusted` is the
authoritative per-caregiver trust fact; policy states whether that fact is required.

Validation separates three decisions:

1. **Feasibility:** full coverage, supported people, trust, availability, calendars, and
   handoffs determine whether the recovery strategy works safely.
2. **Cost:** authoritative caregiver pricing deterministically replaces all model-proposed
   segment and total amounts.
3. **Autonomy:** cost above `automatic_spend_limit` sets `requires_approval=true`. The threshold
   is not a budget, does not invalidate the plan, and must never cause the planner to leave a
   coverage gap. Approval interaction remains a future milestone.

### Handoff abstraction

Maps and routing are intentionally out of scope. Each caregiver may declare a required handoff
buffer, and policy may declare a family-wide minimum. Adjacent assignments to different people
must overlap by exactly the larger required buffer. Less overlap leaves the handoff infeasible;
more overlap is treated as an inconsistent schedule. The primary fixture uses zero-minute
buffers because its handoffs are explicitly assumed feasible.

### Verified live boundary

The Bedrock smoke command executed successfully with `amazon.nova-pro-v1:0`. It invoked all five
context tools once. Attempt 1 was rejected for omitting the `parent_a_standup` calendar change;
attempt 2 repaired that issue but was rejected for omitting the `parent_a_internal_sync` change;
attempt 3 included both changes and passed deterministic validation. Its five coverage segments
spanned 08:00–16:00, all caregivers were inside authoritative availability, deterministic cost
was `$92.00`, and the `$30` threshold produced `requires_approval=true` without a feasibility
error. Model choice remains environment-configurable.

No execution, replanning, approval/resume, persistence, API, external calendar, or UI behavior
is implemented in Milestone 1.

## Milestone 2 implementation

Milestone 2 introduces a separate world-state replanning path around the same Recovery Agent.
A typed `CAREGIVER_DECLINED` `RecoveryEvent` records caregiver, message, relevant window, and
timestamp. `PlanInvalidationService` applies it deterministically:

1. subtract the declined window from the caregiver's authoritative availability;
2. invalidate only active `CAREGIVER_AVAILABLE` assumptions for that caregiver and overlapping
   window, recording reason, time, and triggering event ID;
3. identify impacted coverage segments and newly uncovered windows;
4. identify every other segment as preserved work; and
5. append the event and valid Plan A snapshot to the in-memory `RecoveryCase` history before
   entering `REPLANNING`.

Context tools read a request-local `DemoScenario` snapshot. Initial planning sees the original
fixture; after an event, the same tools see the updated caregiver availability. Preferences,
policy, calendars, and unrelated caregiver facts are unchanged.

The same Strands agent receives the recorded event, invalidated assumptions, active invalidated
plan, impacted/preserved segments, uncovered windows, and refreshed tool context. It proposes a
complete Plan B. `PlanValidator` checks Plan B against the updated scenario. If a Plan B draft is
invalid, the shared bounded draft-repair function may make at most three total Plan B proposals;
this inner repair does not apply another world-state event.

On success, validated Plan B becomes active and the case returns to `EXECUTING`, meaning a valid
plan is ready for later execution behavior. The case is never marked `RESOLVED`. On failure,
invalid Plan B is not activated; the invalidated Plan A remains observable as the active affected
plan and its previously valid snapshot remains in history.

```text
INITIAL PLAN REPAIR                 WORLD-STATE REPLANNING
invalid draft                       previously valid Plan A
unchanged world                     recorded external event
validator feedback                  authoritative state update + impact analysis
same planning cycle                 new Plan B planning cycle
        │                                      │
        └──── bounded validator repair ─────────┘
```

No persistence, approval interaction, external messaging/provider integration, API, UI, or
multi-agent behavior is included.

## Milestone 3 implementation

Milestone 3 separates five decisions that must not be conflated:

1. `PlanValidator` determines feasibility and authoritative cost.
2. `ApprovalService.apply_autonomy_gate` compares that cost to hard `FamilyPolicy`; the LLM never
   decides whether approval is mandatory.
3. A human approve/reject command finalizes the current-plan `ApprovalRequest` idempotently.
4. `RecoveryExecutionService` runs explicit simulated calendar/caregiver actions once.
5. `CompletionVerifier` independently revalidates coverage, authorization, action success,
   dependencies, and internal consistency; it is the only path to `RESOLVED`.

`RecoveryCaseRepository` is the business-logic boundary. `InMemoryRecoveryCaseRepository` stores
deep copies for tests. `DynamoDBRecoveryCaseRepository` stores a complete case as one JSON payload
under the `recovery_case_id` partition key, alongside status, update time, and an optimistic
integer version. Conditional writes reject stale updates. Pydantic JSON preserves aware
datetimes, enums, nested plans/events/assumptions/actions, and Decimal costs without a parallel
serialization format.

When a valid plan exceeds `automatic_spend_limit`, a deterministic request records exact cost,
currency, plan ID, summary, and consequence; the case becomes `APPROVAL_REQUIRED` and is persisted
without execution. Approval reloads that same case and returns it to `EXECUTING`. Duplicate
decisions and executions are idempotent; opposite decisions and stale plan approvals fail.
Rejection records `APPROVAL_REJECTED`, performs no action, and moves the same case to `REPLANNING`
with the rejection event as its latest trigger.

Simulated actions are stable derivations of Plan B: one for each calendar change and caregiver
reservation. Any failure prevents completion. Successful actions still leave the case in
`EXECUTING` until deterministic verification confirms valid full coverage, no pending mandatory
approval, approved consequential spend, every required action succeeded, and no active reliance
on an invalidated assumption.

```text
DISRUPTION → INITIAL PLAN → VALIDATE/REPAIR → VALID PLAN A
    → WORLD CHANGE → INVALIDATE → REPLAN → VALID PLAN B
    → AUTONOMY CHECK → APPROVAL_REQUIRED → PERSIST
    → HUMAN APPROVES → RELOAD SAME CASE → EXECUTE → VERIFY → RESOLVED
```

No FastAPI, UI, real booking/payment/calendar/messaging, provider search, CloudWatch, AgentCore,
or additional agent is included.

### Verified Milestone 3 live boundary

The real DynamoDB harness used `daymend-recovery-cases-dev`. It persisted a valid `$92` Plan B at
`APPROVAL_REQUIRED`, discarded the loaded object, reloaded the same case ID, applied `APPROVED`,
ran four simulated actions, deterministically verified completion, and reloaded `RESOLVED` at
version 4. Valid Plan A history, Grandma's decline, one invalidated assumption, approved request,
and all four execution results survived.

This live storage/workflow harness reuses the deterministic Milestone 2 aggregate fixture;
Milestone 2 already separately proved live Nova Pro replanning. Fresh combined agent runs remain
subject to bounded model variability: recent attempts correctly stopped before persistence when
Nova did not produce a valid Plan A within three attempts. No validator or retry limit was
weakened to force the demo forward.

## Milestone 4 implementation

FastAPI is an adapter, not a workflow engine. The dependency direction is:

```text
HTTP request
    → FastAPI route + API request validation
    → RecoveryApplicationService
    → existing planning / invalidation / approval / execution / completion services
    → RecoveryCaseRepository
    → HTTP response mapper
```

`RecoveryApplicationService` provides four use cases: start a recovery, read a recovery, process
an external event, and decide an approval. The real `StrandsRecoveryPlanningGateway` adapts the
existing initial and world-state planning functions to a narrow injectable boundary. Offline
API tests replace only that model boundary; deterministic validation, invalidation, autonomy,
execution, completion, and persistence code remain real.

Repository construction is selected by `DAYMEND_RECOVERY_REPOSITORY=memory|dynamodb`. AWS region,
table, and model configuration continue through their existing environment settings, outside
routes. The default is in-memory persistence for safe local startup. DynamoDB conditional saves
remain the final concurrency guard; optional request `expected_version` values reject already
stale commands earlier with the same safe `409` semantics.

Public response models deliberately omit `context_state`, model interactions, credentials, and
other internal data. They expose the disruption, active plan, plan-history summaries, events,
invalidated assumptions, pending and historical approvals, execution results, deterministic
cost, trigger, timestamps, and version needed by a later recovery UI. CORS uses a configurable
origin allowlist, with only Angular's `http://localhost:4200` allowed by default. Health checks do
not touch Bedrock or DynamoDB, and startup never creates infrastructure.

The verified live API path used Nova Pro and `daymend-recovery-cases-dev`. HTTP creation produced
Plan A, a caregiver-decline request invalidated one assumption and produced valid `plan_B`, the
API exposed a pending approval, and approval resumed five simulated actions plus deterministic
completion. Recovery case `d436c360-bda5-4625-9521-67d8932f87b0` remained unchanged throughout
and finished `RESOLVED` at version 6.

No Angular, provider marketplace, external calendar/messaging, authentication, AgentCore,
CloudWatch, or additional agent was added.

## Milestone 5 implementation

The Angular 20 frontend remains outside the workflow engine:

```text
Standalone UI components
        ↓ user intent
RecoveryStore (signals)
        ↓ typed command
RecoveryApiService (HttpClient)
        ↓ HTTP
FastAPI → RecoveryApplicationService → deterministic services / Strands / repository
        ↓ complete RecoveryCase response
Presentational components
```

`RecoveryStore` owns the current case, case ID, loading action, and safe error copy. It does not
decide feasibility, approval requirements, invalidation, cost, execution success, or completion.
The typed API service is the only place that constructs endpoint URLs. Angular development uses
`http://localhost:8000`; production defaults to same-origin configuration.

The screen is composed from status hero, subtle demo controls, meaningful recovery timeline,
coverage plan, Plan A change explanation, approval card, execution progress, and resolved summary.
Friendly identity labels and status copy are presentation mappings. Plan-change visualization is
derived from the backend's persisted previous plan and invalidated assumptions. Approval amounts,
automatic-spend limit, execution actions, and final status are backend authoritative.

Milestone 5 adds two safe API fields from existing state: full previous-plan views for the change
visualization and the persisted family policy limit/currency for the approval explanation. It does
not change any Milestone 1–4 business rule. No chat, NgRx, UI framework, provider marketplace,
real external integration, authentication, deployment, or additional agent was added.

## Milestone 6 deployed architecture

```text
Browser
  → CloudFront HTTPS → private S3 Angular bundle + runtime config
  → App Runner HTTPS → FastAPI → RecoveryApplicationService
                                ├→ one Strands Recovery Agent
                                │    → Amazon Bedrock / Nova Pro
                                ├→ deterministic validator / invalidation
                                ├→ deterministic approval / execution / completion
                                └→ DynamoDB RecoveryCase aggregate

App Runner stdout/stderr → CloudWatch Logs (structured safe lifecycle events)
CloudFormation → S3, CloudFront, ECR, App Runner, DynamoDB, IAM
```

Deployment wraps rather than replaces Milestones 1–5. Angular uses a generated runtime API URL
and retains only the current synthetic case ID so a page reload asks FastAPI for authoritative
state. App Runner receives the exact CloudFront CORS origin plus local development origins.
The application role can invoke only regional Nova Pro and read/write only the demo recovery
table. App Runner's service-linked role owns CloudWatch delivery.

The structured event layer is intentionally allow-listed. It records case/plan identifiers,
attempts, validation outcome, latency, model ID, safe tool names, approval/action status, and
completion. It never accepts raw prompts, messages, credentials, tokens, or hidden reasoning.

AgentCore Runtime was initially evaluated as the future host for the reasoning boundary.
Its invocation/session contract is not a drop-in replacement for FastAPI's bounded orchestration.
A safe integration requires a remote `RecoveryPlanningGateway` adapter that preserves structured
repair and replanning semantics while deterministic validation, persistence, approval, execution,
and completion remain outside AgentCore. That split is documented in `docs/deployment.md`; the
Milestone 6.5C later implemented and deployed that adapter; production still does not falsely
claim AgentCore while the hosted IAM integration awaits verification.

## Milestone 6.5A local multi-agent architecture

Production remains the Milestone 6 single-agent deployment. Locally, the opt-in architecture is:

```text
RecoveryApplicationService
  → Recovery Orchestrator Agent
      → transient PlanningBrief
  → Constraint Planner Agent
      → candidate RecoveryPlan
  → deterministic PlanValidator
      → structured findings return only to the same Planner (maximum 3 proposals)
  → existing persistence / autonomy / execution / completion services
```

The split is based on durable reasoning responsibilities. The Orchestrator interprets the
recovery objective and, after a deterministic world-state update, scopes affected versus
preserved work. Its replanning brief carries the triggering event, current case/plan identity,
invalidated assumption IDs, affected windows, preserved segments, and excluded caregiver facts.
Application code overwrites those factual fields from authoritative state; they are not trusted
model assertions and the brief is not persisted.

The Constraint Planner constructs the complete schedule from the brief and all five authoritative
context tools. It alone receives deterministic validator findings and repairs rejected drafts.
The Orchestrator has only childcare-schedule context access; it cannot propose a `RecoveryPlan`.
Neither agent owns exact cost, validity, approval, persistence, execution, or completion.

`DAYMEND_AGENT_ARCHITECTURE=single` is the default and retains the deployed path;
`DAYMEND_AGENT_ARCHITECTURE=multi` enables the local proof. No frontend/API contract or DynamoDB
schema changed. AgentCore and backup-care research remain outside this milestone.

## Milestone 6.5B local backup-care research architecture

Milestone 6.5B preserves `single` and the exact two-agent `multi` path. The opt-in
`multi_research` path contains exactly three reasoning roles:

```text
Recovery Orchestrator Agent
  → deterministic known-option interval analysis
      → sufficient: Constraint Planner Agent
      → insufficient: Backup Care Research Agent
          → search_backup_care (synthetic structured inventory)
          → grounded ranked recommendation
  → Constraint Planner Agent with recommended provider in authoritative context
  → unchanged PlanValidator (maximum 3 proposals)
  → deterministic approval → simulated execution → CompletionVerifier
```

The third role is justified by a durable multi-attribute comparison responsibility. The
Research Agent compares every eligible candidate across price, distance, rating, review count,
prior use, and family preferences; it is not a wrapper that returns the first search result. It
has only `search_backup_care`. The Orchestrator cannot search providers, and the Planner cannot
invoke research.

The provider inventory contains six synthetic records with deliberately competing attributes.
Application code filters full requested-window availability, required verification, required
background check, and child-age support. Those are hard eligibility facts. Eligible candidates
retain soft differences for model ranking. The research contract contains requested windows,
considered/eligible IDs, a complete ranking, concise fit/tradeoffs, a recommended grounded ID,
and unresolved windows. It contains no plan-validity or approval decision. Application code
rejects rankings or recommendations outside the eligible tool result.

The selected candidate is converted to authoritative `Caregiver` context before planning and is
stored in internal `RecoveryCase.context_state` so later validation and completion can rebuild
the same world state. `PlanValidator` overwrites model-proposed autonomy metadata with durable
approval reasons. A valid plan requires approval when cost exceeds the automatic limit, when it
uses an unfamiliar paid external caregiver under configured policy, or both. Approval,
execution, and completion enforce the accepted application-owned plan ID.

The successful live run used one Orchestrator invocation, one Research invocation/tool call, and
two Planner invocations (context plus one accepted proposal), totaling seven Bedrock cycles.
Observed role latency was 7,110 ms Orchestrator, 29,810 ms Research, and 16,650 ms Planner;
end-to-end latency was 53,952 ms. The older 6.5A proof did not retain exact per-role latency or
Bedrock-cycle totals, so an exact numerical delta is not claimed. Structurally, 6.5B adds one
conditional Research invocation and one research tool call; when known options are sufficient,
both remain zero.

No frontend, public API response, production infrastructure, deployment configuration,
marketplace integration, or AgentCore component changed. Production still runs `single`.

## Milestone 6.5C AgentCore boundary

The AgentCore extraction preserves the same three roles and introduces no fourth agent:

```text
RecoveryApplicationService
  → RecoveryPlanningGateway
      ├→ local: in-process Strands roles
      └→ agentcore: IAM-signed InvokeAgentRuntime
            → request-scoped Orchestrator / optional Researcher / Planner
  → PlanValidator (application, maximum three candidates)
  → approval / persistence / execution / completion (application)
```

The serialized `ScenarioContract` is the sole tool context for an invocation. AgentCore rebuilds
the existing immutable `DemoScenario` and binds it through the existing `ContextVar` scopes; it
does not keep a second authoritative store. Initial planning and deterministic-invalidation-based
replanning each return one proposal. If validation fails, the application sends the previous
candidate and only structured `PlanValidationIssue` fields in a new `PLAN_REPAIR` request.

Every logical invocation receives a UUID request ID, also used as a fresh AgentCore runtime
session ID. Sessions provide request correlation only: they are not reused as memory and never
replace the DynamoDB `RecoveryCase`. SDK transport retries are disabled after the first attempt
to avoid ambiguous duplicate model work; planning retry remains exactly three candidates. The
read timeout is 110 seconds because the measured local research path took about 54 seconds.

The runtime response has no case status, approval, execution, completion, raw prompt, or reasoning
field. A runtime cannot mark a case valid or `RESOLVED`. Runtime
`daymend_reasoning-nVUAuPG7rz` is deployed and direct initial/research reasoning is proven with
one Orchestrator, one Research Agent, one Planner, seven model calls, and a valid candidate.
Hosted App Runner authorization proved that invocation checks both the parent runtime and
`runtime-endpoint/DEFAULT`; the template scopes permission to both exact ARNs. With that policy,
App Runner later produced a valid Claude initial plan, but the fixed Grandma-decline demo event
was correctly rejected because that accepted plan did not depend on her. Production was rolled
back. The final showcase now makes movement explicit: CARE segments have locations, TRANSPORT
segments carry origin, destination, driver, and supervision time, and deterministic validation
checks continuity, fixed travel duration, capability, availability, and critical-calendar
conflicts. A bounded local `multi_research` Claude run proved the complete Grandma-dependent
Plan A → decline → research → Plan B → approval → `RESOLVED` path. Production remains
`single + local` until that updated scenario passes one hosted lifecycle.
