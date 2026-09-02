# DayMend Milestones

## Milestone 1 — Core Strands planning

**Goal:** A nanny cancellation causes the agent to gather context through tools, produce a
structured Plan A, and submit it to deterministic validation.

**Status:** Complete. All offline tests and quality checks pass. Live Nova Pro execution invoked
all five tools once, used structured deterministic findings to repair two invalid proposals in
the same agent conversation, and reached a valid third proposal. The final plan covered the full
window, respected availability and calendars, and retained the correct autonomy-threshold
behavior.

**Exit criterion:** An automated test or repeatable local demonstration shows real Strands
reasoning and tool calls producing a typed `RecoveryPlan`, and the deterministic validator
accepts a complete valid plan and rejects representative hard-constraint violations.

Initial validation repair is limited to three proposals while world state is unchanged. It does
not include Milestone 2 invalidation or replanning after an external event.

## Milestone 2 — Plan invalidation and replanning

**Goal:** A caregiver decline invalidates the relevant assumption, recomputes the uncovered
segment, and causes the agent to replan from updated world state.

**Status:** Complete. The event, authoritative availability update, targeted assumption
invalidation, localized impact analysis, Plan A history, same-agent Plan B generation, and
bounded Plan B validation repair are covered by deterministic tests and a real Nova Pro Plan A →
Grandma decline → valid Plan B smoke.

**Exit criterion:** A recorded external decline updates the case without a hardcoded branch,
preserves still-valid plan portions, and produces a newly validated plan for the remaining gap.

Milestone 2 does not execute the plan, persist the case, or implement approval. `EXECUTING`
indicates that a valid replacement plan is ready for later execution work; it is not completion.

## Milestone 3 — Persistence + autonomy + approval/resume

**Goal:** Persist `RecoveryCase` state, apply family policy thresholds, pause for approval, and
resume the same case after an approve or reject decision.

**Status:** Complete. The versioned repository
boundary, single-item DynamoDB adapter, exact serialization, deterministic autonomy gate,
idempotent decisions/execution, rejection transition, and completion verifier are covered by the
full test suite. A real DynamoDB smoke persisted, reloaded, approved, executed, verified, and
reloaded the same `$92` case as `RESOLVED` with all histories intact.

**Exit criterion:** A case survives process restart, an over-threshold action cannot execute
without approval, and both approval outcomes resume the same case with an auditable event trail.

## Milestone 4 — FastAPI

**Goal:** Expose the real recovery workflow through APIs.

**Status:** Complete. FastAPI routes validate and map HTTP data while a thin application service
coordinates the existing workflow boundaries. Offline API tests cover health, create/read,
caregiver decline and replanning, approval/rejection/idempotency, concurrency, safe responses,
CORS, OpenAPI, and a complete same-case lifecycle to `RESOLVED`. A live FastAPI → Nova Pro →
DynamoDB smoke created and resolved case `d436c360-bda5-4625-9521-67d8932f87b0`, with one
invalidated assumption, valid `plan_B`, a persisted approval, five successful simulated actions,
and final version 6.

**Exit criterion:** Documented FastAPI endpoints can create/read a recovery case, accept
external events and approval decisions, advance the actual workflow, and pass API tests.

## Milestone 5 — Angular recovery UI

**Goal:** Show the disruption, recovery progress, plan changes, approval decision, and resolved
outcome without a chatbot UI.

**Status:** Complete. Angular 20 standalone components, a typed API service, and a signal-based
store render the normal day, backend-driven recovery states, meaningful event timeline, friendly
coverage plan, Plan A invalidation/preservation, Plan B, approval boundary, execution results,
and verified completion. Ten Chrome unit tests and the production build pass. A live browser
flow reached Nova Pro, DynamoDB, approval, two successful simulated actions, and `RESOLVED` on
case `d8c9ebdb-b1ac-423b-b6e3-67e20eb8fc92` at version 6.

**Exit criterion:** A parent can follow and act on the primary demo scenario end to end in a
workflow/status interface that accurately reflects backend state.

## Milestone 6 — AWS deployment + observability

**Goal:** Deploy the existing Angular/FastAPI recovery workflow with real Strands, Bedrock,
DynamoDB, scoped IAM, production configuration, and CloudWatch evidence; deploy AgentCore only
if it preserves the proven workflow without a major rewrite.

**Status:** Complete. CloudFormation deploys private S3 + CloudFront, ECR + App Runner, and the
on-demand `daymend-demo-recovery-cases` table. The public browser flow created Plan A, processed
Grandma's decline, produced a valid Plan B, requested and accepted plan-specific approval,
completed seven simulated actions, reached `RESOLVED`, and restored the same version-6 case after
a full page reload. The active App Runner stream contains allow-listed JSON lifecycle events and
real Nova Pro model/tool/latency evidence. Backend tests increased to 88 and Angular tests to 10.
Production CORS and runtime API configuration are verified, and the repository secret scan is
clean after review of one intentional fake redaction-test sentinel.

**AgentCore decision:** **EVALUATED — NOT DEPLOYED.** AgentCore Runtime can host the Strands
reasoning component, but the current workflow performs bounded structured calls around
deterministic validation, request-local tool context, persistence, approval, and completion.
Extracting a remote reasoning gateway plus session/auth/retry semantics is a significant
architecture change; deploying the whole FastAPI service would put deterministic rules in the
wrong boundary. The working App Runner + in-process Strands/Bedrock deployment is retained. See
`docs/deployment.md` for the exact evaluation.

**Exit criterion:** The primary scenario runs in a deployed environment with persistent state,
searchable logs/metrics and documented operations; an explicit decision records whether
AgentCore is used.

## Milestone 6.5A — Recovery orchestration + constraint planning

**Goal:** Prove two materially distinct Strands reasoning roles without changing the deterministic
safety boundary or deployed product behavior.

**Status:** Complete locally; not deployed. The real Recovery Orchestrator produces a transient,
authoritatively normalized `PlanningBrief`, while the real Constraint Planner owns Plan A/Plan B
construction and the unchanged three-proposal validator-repair loop. The single-agent path remains
the default and production architecture.

A single live Nova Pro lifecycle used case
`daymend-multi-dda7ca5c-3b15-47ce-bc56-48699635e332`. Initial planning reached valid `$92` Plan A
on attempt 2. Grandma's typed decline deterministically invalidated one assumption and preserved
five plan segments. The replanning Orchestrator ran from that changed state, and the Planner
reached valid `$114` Plan B on attempt 3. Deterministic policy requested approval, approval resumed
the same case, all six simulated actions succeeded, and `CompletionVerifier` set `RESOLVED` at
version 6. The final reporting serializer failed after resolution because it expected the initial
result's attempt field name; that local reporting bug is fixed and regression-tested without a
second live run.

**Exit criterion:** Both real Strands agents participate in initial and world-change planning; a
live same-case lifecycle reaches deterministic `RESOLVED`; single-agent fallback, validator rules,
retry cap, approval, execution, and completion remain unchanged.

## Milestone 6.5B — Backup care research

**Goal:** Add the third and final reasoning role only for recovery gaps that current known options
cannot cover, while retaining deterministic eligibility, validation, approval, and completion.

**Status:** Complete locally; not deployed. `multi_research` adds a real Strands Backup Care
Research Agent with only the `search_backup_care` tool. A dedicated fixture leaves 10:00–12:00
uncovered after considering both parents and known caregivers. Deterministic search evaluates six
synthetic provider records and exposes three eligible candidates for meaningful soft-preference
ranking. Grounding checks reject invented or omitted eligible IDs before the recommendation can
reach the Constraint Planner.

The one controlled Nova Pro lifecycle used case
`daymend-research-f98e0e7b-f47f-45d3-8485-9627c77bc9ef`. The Research Agent ranked
`harbor_nanny_coop`, `willow_family_care`, and `bright_start_agency`, recommending
`harbor_nanny_coop`. The Planner's first proposal passed unchanged `PlanValidator` at `$142`.
Application code assigned
`daymend-research-f98e0e7b-f47f-45d3-8485-9627c77bc9ef:plan:1`; deterministic policy requested
approval for above-limit cost and unfamiliar paid care. Approval resumed the same case, all
three simulated reservations succeeded, and `CompletionVerifier` set `RESOLVED` at version 5.

The run recorded one Orchestrator invocation, one Research Agent invocation, one research tool
call, two Planner invocations, seven total Bedrock cycles, and 53,952 ms total latency. Role
latencies were 7,110 ms, 29,810 ms, and 16,650 ms respectively. The prior 6.5A run did not retain
exact role/cycle timing, so the honest architectural comparison is one additional conditional
research role and tool call, with zero research overhead on sufficient known-option scenarios.

**Exit criterion:** Exactly three specialized Strands roles participate when research is needed;
hard eligibility and approval remain deterministic; grounded researched care reaches a valid
accepted plan and verified completion; `single` and `multi` regressions remain green; production
and AgentCore remain unchanged.

## Milestone 7 — Submission polish

**Goal:** Prepare the architecture diagram, README, tests, public repository, license, demo
video, and Devpost submission.

**Exit criterion:** Submission materials accurately describe the verified build, the public
repository is runnable from its documentation, the demo video shows the primary scenario, and
all event requirements have been checked before submission.
