# DayMend milestone summary

This document summarizes the path to the submitted system. Earlier model and architecture
experiments are historical and are not the current deployment.

## 1. Validated childcare recovery plan

Established the core `RecoveryPlan`, five authoritative context categories, structured model
output, and an independent deterministic validator. The model proposes; deterministic code checks
coverage, eligibility, calendars, handoffs, travel, transport, and policy.

## 2. World-state change and replanning

Added typed external events, assumption invalidation, uncovered-window calculation, preserved
segments, and Plan B generation on the same recovery lifecycle.

## 3. Persistent approval and completion

Introduced the versioned `RecoveryCase`, in-memory and DynamoDB repositories, deterministic cost
and autonomy policy, approval/rejection, idempotent simulated execution, and final completion
verification. `RESOLVED` became reachable only through deterministic verification.

## 4. FastAPI application boundary

Added the thin HTTP API and `RecoveryApplicationService`. Routes map requests; application
services coordinate planning, invalidation, policy, persistence, execution, and completion.

## 5. Parent-facing Angular experience

Built the status-driven recovery UI: disruption action, Plan A, caregiver decline, What Changed,
Plan B recommendation, approval, execution, resolution, and persistence after reload.

## 6. Hosted AWS application

Deployed Angular through CloudFront/S3, FastAPI through App Runner, DynamoDB persistence,
least-privilege IAM, and CloudWatch observability.

## 6.5A. Three-agent responsibility split

Separated durable reasoning responsibilities into exactly three Strands agents:

1. Recovery Orchestrator;
2. Constraint Planner;
3. Backup Care Research.

Deterministic services remained application code rather than becoming extra agents. Local and
remote repair paths were unified around one explicit `PlannerInvocationInput` so correctness no
longer depends on conversation history.

## 6.5B. Conditional synthetic backup-care research

Added deterministic known-option exhaustion detection and conditional research over synthetic
provider inventory. Hard eligibility remains deterministic; the research agent ranks eligible
options. There is no Care.com or real provider-marketplace integration.

## 6.5C. AgentCore production reasoning

Moved only the three-agent reasoning layer into Amazon Bedrock AgentCore Runtime. The deployed v12
runtime uses Python 3.12 and Claude Sonnet 4.5 via
`us.anthropic.claude-sonnet-4-5-20250929-v1:0`.

App Runner retains the authoritative lifecycle, validator, approval, execution, completion, and
DynamoDB persistence. Runtime requests are versioned and stateless. One narrow transport retry
protects connection-establishment/connection-closed failures without retrying ambiguous or
application-level failures.

## Final reliability and demo polish

Initial planning now uses a generic `FeasibleAssignmentMatrix` and explicit
`FeasibleTransportPrimitive` records derived from authoritative data. This removed duplicated raw
initial context and excludes impossible caregiver/transport combinations without constructing the
answer for Claude.

Preservation-aware Plan B uses authoritative primitive-ID selection when the feasible matrix can
materialize the complete repair. Immutable preserved primitives are required, exact segments are
materialized deterministically, and a post-research planability gate rejects infeasible providers
before Planner execution.

The final hosted proof achieved:

- valid Plan A on Planner attempt 1, about 32.0 seconds server-side;
- a real Grandma-dependent plan and decline event;
- material preservation/invalidation of Plan A segments;
- one Backup Care Research invocation;
- valid Plan B on Planner attempt 1, about 60.5 seconds;
- Harbor Nanny Coop selected from fictional provider inventory;
- deterministic cost `$94.50` and approval above `$30`;
- two successful simulated actions;
- deterministic completion, `RESOLVED`, and persistence after reload;
- healthy SSE live progress and no browser console errors.

The editorial frontend, responsive Plan B recommendation, rejection behavior, and DayMend favicon
were verified in production. At submission cleanup, 231 backend tests and 89 frontend tests passed.

## Submitted state

The application code is frozen. Current production is:

```text
CloudFront/S3 Angular
→ App Runner FastAPI
→ RecoveryApplicationService
→ AgentCore v12
→ 3 Strands agents
→ Claude Sonnet 4.5

Deterministic feasibility, validation, policy, execution,
completion, and DynamoDB persistence remain application-owned.
```
