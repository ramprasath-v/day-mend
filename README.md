# DayMend

> “When childcare falls through, your whole day shouldn’t.”

**Watch demo — video link coming soon** · **[Try live demo](https://d28bm0qb8qheeh.cloudfront.net/)**

When a backup caregiver declines, DayMend repairs only the affected coverage, preserves what still
works, and asks the parent only when a real decision is needed.

> **What is real / what is simulated:** Strands agents, AgentCore, Claude Sonnet 4.5, validation,
> replanning, approval policy, persistence, and live orchestration are real. Backup-provider
> inventory is synthetic; booking, calendar, messaging, and payment execution are simulated.
> `RESOLVED` means deterministic completion within the demo scenario and simulated execution
> results.

DayMend is a childcare disruption recovery agent for working parents, built for the
**Everyday Agents / Agents for Humans** category. When normal childcare suddenly becomes
unavailable, DayMend rebuilds the whole day: care coverage, parent calendars, trusted helpers,
travel and handoffs, cost, approval, execution, and final verification.

It is not a generic family assistant or a backup-care marketplace. DayMend maintains one
persistent `RecoveryCase`, reacts to real world-state changes, preserves plan segments that still
work, and pauses only when the parent must make a consequential decision.

## Why this needs an agent

Childcare recovery is a changing coordination problem, not a lookup. The system must interpret a
disruption, understand the family’s day, compare feasible combinations, respond when an assumption
becomes false, and propose a complete new plan.

DayMend deliberately separates reasoning from authority:

> **Agents propose. Deterministic services own truth.**

- **Agents reason and propose.** They interpret the disruption, coordinate planning, rank feasible
  options, research synthetic backup care when needed, and produce structured plan candidates.
- **Deterministic application code owns truth.** It computes feasibility, validates every minute of
  coverage, enforces caregiver and transport constraints, calculates cost, applies policy, gates
  execution on approval, and verifies completion.

The model cannot declare its own plan valid. A case cannot become `RESOLVED` until deterministic
completion verification succeeds.

## The submitted experience

The proven demo follows one continuous recovery:

1. The nanny becomes unavailable.
2. DayMend builds and deterministically validates Plan A.
3. Plan A depends on Grandma for part of the day.
4. Grandma declines, changing authoritative world state.
5. DayMend identifies invalidated coverage and materially preserved Plan A segments.
6. Known family options are insufficient, so Backup Care Research runs once.
7. The Planner proposes a valid Plan B using Harbor Nanny Coop from synthetic provider inventory.
8. Deterministic cost is `$87.75`, above the family’s `$30` automatic-spend threshold.
9. DayMend pauses for human approval.
10. Approval resumes the same `RecoveryCase`; two simulated actions execute successfully.
11. Deterministic completion verification passes and the case becomes `RESOLVED`.
12. Reloading the page returns the same versioned case from DynamoDB.

The Angular experience streams safe, structured progress during long-running reasoning. It shows
what DayMend is doing, what changed, which coverage was preserved or replaced, and when the parent
must decide—without exposing prompts or chain-of-thought.

## Architecture

![DayMend architecture: Angular and FastAPI application flow, three-agent AgentCore reasoning layer, and deterministic control services](docs/assets/daymend-architecture.png)

```text
Angular on CloudFront/S3
        ↓
FastAPI on App Runner
        ↓
RecoveryApplicationService
        ↓
Amazon Bedrock AgentCore Runtime (deployed v12)
        ↓
Recovery Orchestrator Agent
        ├── Constraint Planner Agent
        └── Backup Care Research Agent (only when needed)
        ↓
Claude Sonnet 4.5 on Amazon Bedrock
```

Alongside that reasoning path, deterministic services remain in the FastAPI application:

```text
feasibility normalization → validation → policy/approval → execution guards
→ completion verification → DynamoDB persistence/versioning
```

The production model is the Claude Sonnet 4.5 inference profile:

```text
us.anthropic.claude-sonnet-4-5-20250929-v1:0
```

### The three agents

1. **Recovery Orchestrator Agent** turns the disruption or world-state change into a focused
   planning brief and coordinates the reasoning operation.
2. **Constraint Planner Agent** composes a complete `RecoveryPlan` candidate and repairs only from
   explicit structured validator feedback when necessary.
3. **Backup Care Research Agent** ranks eligible records from the synthetic provider fixture only
   when deterministic interval analysis proves known options cannot cover the affected window.

Deterministic services are not additional agents.

### Feasibility before generation

For initial planning, application code converts authoritative schedules, calendars, caregiver
facts, locations, travel durations, and policy into a `FeasibleAssignmentMatrix`. Its
`FeasibleTransportPrimitive` entries bind an allowed transporter, permitted window, origin,
destination, and required duration. Invalid combinations are excluded before the Planner sees
them, while Claude still chooses how to combine feasible care and transport primitives into a
whole-day plan.

The independent `PlanValidator` remains the source of truth. A bounded repair loop allows at most
three plan proposals; the limit and validation rules are never relaxed.

```text
Candidate plan → deterministic validator
  → structured validator feedback if invalid → Planner repair → revalidation
```

Backup Care Research runs conditionally when known care options cannot cover the disruption.

## Responsibility boundary

| Agents may | Deterministic code must |
| --- | --- |
| Interpret the disruption | Normalize feasible assignments |
| Produce the planning brief | Enforce complete continuous coverage |
| Compose and repair plan candidates | Enforce caregiver trust and availability |
| Rank feasible synthetic backup options | Validate locations, travel, transport, and handoffs |
| Recommend next actions | Calculate cost and apply hard family policy |
| Explain the proposed recovery | Require and record approval |
|  | Guard idempotent execution |
|  | Verify completion before `RESOLVED` |
|  | Persist and version the complete `RecoveryCase` |

## Live Recovery orchestration

The live timeline shows structured backend progress through planning, validation, research,
approval, execution, and completion. AgentCore-internal details may arrive when its response
returns. For SSE, event deduplication, and transport retry details, see
[Live progress and observability](docs/architecture.md#live-progress-and-observability).

## One verified hosted lifecycle

These results describe one verified hosted lifecycle. The timings are individual observations,
not averages, benchmarks, or reliability rates.

| Evidence | Observed result |
| --- | --- |
| AgentCore runtime | v12 |
| Plan A | Valid on first Planner attempt |
| Plan A server latency | 32.031s |
| Plan B | Valid on first Planner attempt |
| Plan B server latency | 60.495s |
| Deterministic cost | $87.75 |
| Automatic-spend threshold | $30; human approval required |
| Execution | 2 simulated actions succeeded |
| Completion | Deterministically verified |
| Final status | `RESOLVED` |
| Persistence | Reload verified |

Deployment details:

- Frontend: <https://d28bm0qb8qheeh.cloudfront.net/>
- Backend health: <https://5zvgskmgiu.us-east-1.awsapprunner.com/health>
- Region: `us-east-1`
- Reasoning runtime: Amazon Bedrock AgentCore, deployed v12
- Architecture: `multi_research`
- Model: `us.anthropic.claude-sonnet-4-5-20250929-v1:0`
- Persistence: DynamoDB table `daymend-demo-recovery-cases`

The public demo is unauthenticated and uses synthetic family and provider data.

> **Synthetic-data disclosure:** Harbor Nanny Coop and every backup-care provider record are
> fictional demo fixtures. DayMend does not integrate with Care.com or any real provider
> marketplace. Booking, payment, calendar, and messaging actions are simulated.

## Repository structure

```text
.
├── backend
│   ├── app
│   │   ├── agent          # Strands agents and AgentCore contracts
│   │   ├── api            # FastAPI routes and schemas
│   │   ├── application    # Recovery lifecycle coordination
│   │   ├── fixtures       # Synthetic family/provider scenario
│   │   ├── models         # RecoveryCase and plan contracts
│   │   ├── repositories   # Memory and DynamoDB persistence
│   │   ├── services       # Validation, policy, execution, completion
│   │   └── tools          # Authoritative read-only context tools
│   └── tests
├── frontend               # Angular recovery experience and SSE client
├── infra                  # CloudFormation for AWS resources
├── scripts                # Existing deployment entry points
└── docs                    # Architecture, demo, deployment, and milestones
```

## Local setup

The FastAPI backend supports Python 3.11 or newer and uses
[`uv`](https://docs.astral.sh/uv/) for local dependency management. The deployed AgentCore runtime
uses Python 3.12.

```bash
cd backend
uv sync --dev
```

AWS credentials are resolved through the normal AWS SDK credential chain and must not be stored in
the repository. To run the real local three-agent reasoning path, configure Bedrock access:

```bash
export AWS_REGION=us-east-1
export DAYMEND_AGENT_RUNTIME=local
export DAYMEND_AGENT_ARCHITECTURE=multi_research
export DAYMEND_BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-5-20250929-v1:0
```

Start the API with process-local persistence:

```bash
export DAYMEND_RECOVERY_REPOSITORY=memory
export DAYMEND_ALLOWED_ORIGINS=http://localhost:4200,http://127.0.0.1:4200
.venv/bin/uvicorn app.main:app --reload --port 8000
```

In another terminal, start Angular:

```bash
cd frontend
npm install
npm start
```

Development points to `http://localhost:8000`. Production obtains its API URL at runtime from
`frontend/public/config.js`; the tracked template is intentionally empty and the deployment path
writes the hosted value into the generated build artifact.

## API surface

- `GET /health`
- `POST /recoveries`
- `GET /recoveries/{recovery_case_id}`
- `POST /recoveries/{recovery_case_id}/events`
- `POST /recoveries/{recovery_case_id}/approvals/{approval_id}`
- `GET /progress/{progress_id}`
- `GET /progress/{progress_id}/stream`
- `GET /recoveries/{recovery_case_id}/progress`

Mutation requests use optimistic `expected_version` checks where applicable. Approval resumes the
same case; rejection performs no execution and cannot produce `RESOLVED`.

## Tests and quality

Verified at code freeze:

- Backend: **167 tests passed**
- Frontend: **24 tests passed**
- Ruff lint: passed
- Ruff formatting check: passed
- Python `compileall`: passed
- Angular production build: passed
- `git diff --check`: passed

Run the checks locally:

```bash
cd backend
.venv/bin/python -m pytest
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python -m compileall -q app tests agentcore_runtime.py

cd ../frontend
npm test -- --watch=false --browsers=ChromeHeadless
npm run build
```

## More documentation

- [Architecture and safety boundaries](docs/architecture.md)
- [Proven demo flow](docs/demo-flow.md)
- [AWS deployment](docs/deployment.md)
- [Milestone summary](docs/milestones.md)

## License

DayMend is available under the [MIT License](LICENSE).
