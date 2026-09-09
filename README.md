# DayMend

> “When childcare falls through, your whole day shouldn’t.”

DayMend is a childcare disruption recovery agent for working parents. When normal childcare
unexpectedly falls through, the problem is larger than finding an available babysitter: the
parent must reconcile coverage windows, calendars, trusted people, handoffs, costs, family
preferences, approvals, and changing responses while the workday is already beginning.

DayMend recovers that day end to end. Unlike a backup-care marketplace, it maintains a recovery
case, gathers the family's relevant context, proposes coordinated coverage and calendar changes,
reacts when assumptions become false, pauses only for meaningful approval decisions, resumes the
same case, and verifies that coverage was actually restored.

## Why an agent

Recovery is a changing decision process rather than a fixed lookup. An agent is useful for
understanding the disruption, choosing which context and tools it needs, reasoning over hard and
soft preferences, proposing a recovery strategy, and deciding what to repair after an external
change.

The agent does not get the final word on safety or completion. Deterministic code must validate
coverage, trust, availability, overlaps, handoffs, travel feasibility, spending limits, approval
requirements, action outcomes, and final completion. The LLM proposes a plan; deterministic code
decides whether it is valid. A case cannot become `RESOLVED` until final deterministic coverage
verification succeeds.

## Recovery loop

1. Record a disruption as a persistent `RecoveryCase`.
2. Gather current family, calendar, caregiver, availability, and policy context.
3. Have one Strands Recovery Agent produce a structured `RecoveryPlan`.
4. Validate all hard constraints deterministically; during initial planning, return structured
   findings to that same agent for at most two repairs (three proposals total).
5. Accept only a valid Plan A, then execute valid actions and observe their real outcomes.
6. Continue, replan from updated state, or request approval as needed.
7. Resume the same case after a decision or response.
8. Mark the case `RESOLVED` only after deterministic completion verification.

## Current status

**Milestone 1 — COMPLETE.** The repository contains one real Strands Recovery Agent, five
read-only context tools, typed structured plan output, the synthetic primary scenario, and an
independent deterministic validator. Initial planning now has a bounded validation-and-repair
loop: context is gathered once, each proposal is validated, and structured findings are returned
to the same agent for up to three total proposals. A real Nova Pro smoke invoked all five tools,
repaired two rejected drafts, and reached `valid=true` on attempt 3. The final plan fully covered
08:00–16:00, respected caregiver availability and parent calendars, cost `$92.00`
deterministically, and correctly reported `requires_approval=true` against the `$30` automatic
spend threshold. All offline tests and quality checks pass.

**Milestone 2 — COMPLETE.** A typed caregiver-decline event updates request-local authoritative
world state, invalidates only matching plan assumptions, calculates impacted and preserved
segments plus newly uncovered windows, and sends that state to the same Recovery Agent. A real
Nova Pro smoke produced a deterministically valid Plan B while retaining valid Plan A in history.

**Milestone 3 — COMPLETE.** Complete `RecoveryCase`
aggregates now round-trip through in-memory or DynamoDB repositories. Deterministic policy pauses
a valid `$92` plan at `APPROVAL_REQUIRED` because it exceeds the `$30` autonomy limit. A later
approve/reject command reloads and resumes the same versioned case. Approved simulated actions
execute exactly once, and only the deterministic completion verifier can set `RESOLVED`. A real
`daymend-recovery-cases-dev` DynamoDB smoke persisted and reloaded the same case through approval,
four successful actions, completion verification, and final `RESOLVED` state at version 4.

**Milestone 4 — COMPLETE.** A thin FastAPI boundary now exposes health, recovery creation/read,
external caregiver events, and approval decisions. `RecoveryApplicationService` coordinates the
existing planning, invalidation, repository, autonomy, execution, and completion services; routes
contain no recovery policy or persistence logic. The offline HTTP lifecycle reaches `RESOLVED`
through the real deterministic services, and a live Nova Pro + DynamoDB API smoke resolved the
same case after Plan B approval.

**Milestone 5 — COMPLETE.** The Angular 20 recovery experience turns the API lifecycle into a
polished status screen rather than a chatbot. Parents can trigger the synthetic disruption, watch
Plan A appear, submit Grandma's real decline event, see the invalidated and preserved Plan A
segments, review Plan B against the automatic-spend boundary, approve or reject, and see
backend-derived execution plus deterministic `RESOLVED` completion. A live browser smoke used
Nova Pro and DynamoDB end to end.

**Milestone 6 — COMPLETE.** DayMend is deployed in `us-east-1` with Angular on private S3 behind
CloudFront, FastAPI on App Runner, Nova Pro through Strands/Bedrock, and the existing complete
`RecoveryCase` aggregate in an on-demand DynamoDB table. A public browser smoke created Plan A,
processed Grandma's decline, invalidated and replanned, paused at the `$30` autonomy boundary,
approved a fresh `$114` Plan B, completed seven simulated actions, reached `RESOLVED`, and
restored the same version-6 case after a full page reload. App Runner streams safe structured
lifecycle and Bedrock telemetry to CloudWatch. AgentCore was seriously evaluated and not
deployed; the exact boundary decision is in [`docs/deployment.md`](docs/deployment.md).

**Milestone 6.5A — COMPLETE LOCALLY, NOT DEPLOYED.** An opt-in
`DAYMEND_AGENT_ARCHITECTURE=multi` path now separates recovery-level orchestration from
constraint planning. A real Strands Recovery Orchestrator turns authoritative disruption or
world-change state into a transient `PlanningBrief`; a separate real Strands Constraint Planner
uses the five context tools and owns `RecoveryPlan` proposal plus validator-feedback repair. A
live Nova Pro lifecycle produced valid Plan A, deterministically invalidated Grandma's affected
assumption, preserved five segments, produced valid `$114` Plan B within the unchanged
three-proposal cap, approved it, completed six simulated actions, and reached deterministic
`RESOLVED` on the same case at version 6. Production and the default remain `single` pending a
separate deployment decision.

**Milestone 6.5B — COMPLETE LOCALLY, NOT DEPLOYED.** A separate
`DAYMEND_AGENT_ARCHITECTURE=multi_research` mode adds the third and final reasoning role: a real
Strands Backup Care Research Agent. Deterministic interval analysis invokes it only when known
family options cannot cover a required window. Its only tool searches six realistic but fully
synthetic provider records, deterministically removes hard-ineligible candidates, and leaves
price, distance, rating, reviews, and prior-use tradeoffs for grounded model ranking. The
recommended candidate enters authoritative Planner/Validator context; deterministic policy—not
the Research Agent—requires approval for unfamiliar paid care and/or cost above the automatic
limit.

The controlled Nova Pro proof resolved case
`daymend-research-f98e0e7b-f47f-45d3-8485-9627c77bc9ef`. Known options left 10:00–12:00
uncovered. Research considered six candidates, ranked three eligible candidates, and recommended
`harbor_nanny_coop`. The Planner produced a valid `$142` plan on proposal 1, application code
assigned `<case>:plan:1`, one approval authorized both consequential reasons, three simulated
actions succeeded, and deterministic completion set `RESOLVED` at version 5. This is not a
marketplace integration: provider data is synthetic; Strands reasoning/ranking, validation,
approval, persistence behavior, and completion are real. Production remains unchanged on
`single`, and AgentCore remains unimplemented.

These are deliberately separate mechanisms:

- **Initial-plan repair:** a draft was never valid; world state is unchanged; validator findings
  correct the draft.
- **World-state replanning:** Plan A was valid; a recorded external event changes authoritative
  facts; deterministic impact analysis begins a new Plan B planning cycle.

Execution still uses simulated explicit actions only; there is no real booking, payment,
calendar, messaging, authentication, or frontend integration.

## Preferences, policy, and trust

`FamilyPreferences` contains soft priorities used by the agent to rank otherwise valid plans,
such as preferring family coverage or fewer handoffs. A preference violation can produce a
validator warning but cannot make a plan invalid.

`FamilyPolicy` contains hard rules enforced by deterministic code, including caregiver trust,
whether unapproved caregivers may be used, the automatic-spend boundary, and the minimum
handoff buffer. `Caregiver.is_trusted` is the sole authoritative trust state for an individual
caregiver; policy does not duplicate a caregiver allowlist.

The automatic-spend limit determines whether a valid proposal would require approval before
execution. It is not a planning budget: exceeding it does not make an otherwise feasible plan
invalid, and coverage must never be sacrificed to avoid approval. Milestone 1 reports the
boundary; Milestone 3 deterministically pauses and resumes execution around it.

## Repository structure

```text
.
├── AGENTS.md
├── LICENSE
├── README.md
├── backend
│   ├── app
│   │   ├── agent
│   │   ├── api
│   │   ├── fixtures
│   │   ├── models
│   │   ├── repositories
│   │   ├── services
│   │   └── tools
│   ├── tests
│   └── pyproject.toml
├── frontend
│   ├── src/app
│   ├── angular.json
│   └── package.json
├── infra
│   ├── foundation.yaml
│   └── service.yaml
├── scripts
│   └── deploy-aws.sh
└── docs
    ├── architecture.md
    ├── deployment.md
    ├── demo-flow.md
    └── milestones.md
```

## Local setup

Prerequisites: Python 3.11 or newer and
[`uv`](https://docs.astral.sh/uv/getting-started/installation/).

```bash
cd backend
uv sync --dev
```

The project uses `strands-agents` with its native Amazon Bedrock provider. AWS credentials are
resolved through the normal AWS SDK credential chain and are never stored in this repository.
Configure a region and, optionally, override the default model:

```bash
export AWS_REGION=us-west-2
export DAYMEND_BEDROCK_MODEL_ID=global.anthropic.claude-sonnet-4-6
```

Your AWS identity must have Bedrock model access and permission to invoke the configured model.
Run the real planning and validation smoke path from `backend/`:

```bash
uv run python -m app.agent.demo
```

Run the live Milestone 2 Plan A → caregiver decline → Plan B smoke:

```bash
DAYMEND_BEDROCK_MODEL_ID=amazon.nova-pro-v1:0 \
uv run python -m app.agent.replanning_demo
```

For DynamoDB-backed Milestone 3 development, configure the table and create it if absent:

```bash
export DAYMEND_RECOVERY_TABLE=daymend-recovery-cases-dev
uv run python -m app.repositories.dynamodb_setup
```

The table uses `recovery_case_id` as its string partition key and on-demand billing. Each case is
one versioned item whose `payload` is the complete Pydantic JSON aggregate; no secrets or model
reasoning are stored. Run the live persistence/approval/resume smoke with:

```bash
DAYMEND_RECOVERY_TABLE=daymend-recovery-cases-dev \
uv run python -m tests.live_dynamodb_approval_smoke
```

That harness uses the deterministically validated Milestone 2 test aggregate and proves the real
DynamoDB/service lifecycle, not fresh model behavior. To combine fresh Nova Pro planning with the
same DynamoDB lifecycle, run:

```bash
DAYMEND_BEDROCK_MODEL_ID=amazon.nova-pro-v1:0 \
DAYMEND_RECOVERY_TABLE=daymend-recovery-cases-dev \
uv run python -m app.agent.approval_demo
```

The combined command preserves the strict three-attempt planning cap and may stop before
persistence if a fresh model session does not produce a valid Plan A or Plan B.

The smoke output contains the configured model ID, tools used, proposal and validation summaries
for each attempt, and the final safety/cost/autonomy result. It does not expose model
chain-of-thought.

Run the local opt-in two-agent lifecycle proof without changing the deployed architecture:

```bash
DAYMEND_AGENT_ARCHITECTURE=multi \
DAYMEND_BEDROCK_MODEL_ID=amazon.nova-pro-v1:0 \
AWS_REGION=us-east-1 \
uv run python -m app.agent.multi_agent_demo
```

Omitting `DAYMEND_AGENT_ARCHITECTURE` deliberately retains the proven single-agent path.

Run the dedicated three-agent research lifecycle against the synthetic provider fixture:

```bash
DAYMEND_AGENT_ARCHITECTURE=multi_research \
DAYMEND_BEDROCK_MODEL_ID=amazon.nova-pro-v1:0 \
AWS_REGION=us-east-1 \
uv run python -m app.agent.backup_care_demo
```

This command performs one controlled lifecycle. It does not retry a failed live run beyond the
existing three-proposal Planner cap and prints only safe structured diagnostics.

Run the offline tests and quality checks:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

## FastAPI

Run the local API from `backend/` with process-local persistence:

```bash
export DAYMEND_RECOVERY_REPOSITORY=memory
export DAYMEND_ALLOWED_ORIGINS=http://localhost:4200
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Use `DAYMEND_RECOVERY_REPOSITORY=dynamodb` plus `DAYMEND_RECOVERY_TABLE` and `AWS_REGION`
for the AWS demo repository. Planning uses `DAYMEND_BEDROCK_MODEL_ID` through the existing
Recovery Agent configuration. Startup never creates a DynamoDB table; use the explicit setup
helper above.

The API exposes:

- `GET /health`
- `POST /recoveries`
- `GET /recoveries/{recovery_case_id}`
- `POST /recoveries/{recovery_case_id}/events`
- `POST /recoveries/{recovery_case_id}/approvals/{approval_id}`

Interactive OpenAPI documentation is available at `/docs`, with the schema at `/openapi.json`.
Mutation requests may include `expected_version`; stale versions return `409` without overwriting
newer state. CORS origins are a comma-separated allowlist and default only to
`http://localhost:4200`.

Example create request:

```json
{
  "disruption_type": "CHILDCARE_UNAVAILABLE",
  "occurred_at": "2026-08-27T07:02:00-07:00",
  "caregiver_id": "nanny",
  "message": "I'm sick and can't come today."
}
```

Run the live API lifecycle smoke with:

```bash
AWS_REGION=us-east-1 \
DAYMEND_BEDROCK_MODEL_ID=amazon.nova-pro-v1:0 \
DAYMEND_RECOVERY_REPOSITORY=dynamodb \
DAYMEND_RECOVERY_TABLE=daymend-recovery-cases-dev \
.venv/bin/python -m tests.live_api_smoke
```

## Angular demo UI

Install and run the Angular 20 frontend:

```bash
cd frontend
npm install
npm start
```

Development uses `http://localhost:8000` from Angular's development environment. Start the
backend separately with CORS configured for the frontend:

```bash
cd backend
export DAYMEND_ALLOWED_ORIGINS=http://localhost:4200,http://127.0.0.1:4200
.venv/bin/uvicorn app.main:app --reload --port 8000
```

For the live AWS demo, add the Nova Pro, DynamoDB repository, region, and table environment
variables shown above before starting Uvicorn. Then open `http://localhost:4200`, click
**Simulate nanny cancellation**, **Simulate Grandma decline**, and the plan-specific approval.
The UI never fabricates a plan or completion state; it renders each returned `RecoveryCase`.

Production loads its API endpoint from `public/config.js`, which the deployment script generates
after App Runner is available. No source edit is needed between local and hosted use. The browser
stores only the current synthetic recovery-case ID and reloads that case from the API after a
page refresh.

Frontend verification:

```bash
npm test -- --watch=false --browsers=ChromeHeadless
npm run build
```

## Hosted AWS demo

- Frontend: <https://d28bm0qb8qheeh.cloudfront.net>
- Backend health: <https://5zvgskmgiu.us-east-1.awsapprunner.com/health>
- Region: `us-east-1`
- Model: `amazon.nova-pro-v1:0`
- Persistence: `daymend-demo-recovery-cases` (DynamoDB, on demand)

The demo is public, unauthenticated, and uses synthetic data only. Click **Simulate nanny
cancellation**, then **Simulate Grandma decline**, approve the plan-specific amount if requested,
and refresh the page after `RESOLVED` to verify persisted state. Fresh model runs may choose a
different valid plan and cost; the stable behavior is deterministic coverage validation and an
approval pause whenever cost exceeds the `$30` automatic-spend limit.

AWS services used are CloudFormation, ECR, App Runner, Bedrock, DynamoDB, S3, CloudFront,
CloudWatch Logs, and IAM. Deployment, resource names, least-privilege runtime policy, operations,
observability evidence, and AgentCore evaluation are documented in
[`docs/deployment.md`](docs/deployment.md). Reproduce the deployment with:

```bash
AWS_REGION=us-east-1 \
DAYMEND_BEDROCK_MODEL_ID=amazon.nova-pro-v1:0 \
./scripts/deploy-aws.sh
```

## Roadmap

The planned increments are core Strands planning; plan invalidation and replanning; persistence,
autonomy, and approval/resume; FastAPI; an Angular recovery UI; AWS deployment and observability;
and submission polish. Each milestone and its exit criterion is documented in
[`docs/milestones.md`](docs/milestones.md).

The primary end-to-end scenario is documented in
[`docs/demo-flow.md`](docs/demo-flow.md), and architectural boundaries are documented in
[`docs/architecture.md`](docs/architecture.md).

The fixture is deterministic and synthetic. Tool selection and structured plan generation in
the smoke path are performed by the real Strands/Bedrock agent; no Plan A is hardcoded.

## AgentCore runtime boundary (Milestone 6.5C)

The backend now has separate architecture and runtime switches:

```bash
DAYMEND_AGENT_ARCHITECTURE=single|multi|multi_research
DAYMEND_AGENT_RUNTIME=local|agentcore
DAYMEND_AGENTCORE_RUNTIME_ARN=arn:aws:bedrock-agentcore:...
```

`local` remains the default. The AgentCore path sends a versioned, request-scoped scenario to a
stateless reasoning runtime. AgentCore returns one `RecoveryPlan` candidate (plus a structured
brief/research result); FastAPI validates it and can send safe validator issues back in another
invocation, up to the unchanged three-attempt cap. Validation, exact cost, approval, persistence,
execution, and `RESOLVED` remain application-owned.

Deployment is isolated in `infra/agentcore.yaml` and `scripts/deploy-agentcore.sh`. Runtime
`daymend_reasoning-nVUAuPG7rz` is deployed and direct initial/research invocations are proven.
The App Runner integration proved that AgentCore authorizes both the parent runtime ARN and its
`DEFAULT` endpoint ARN; the least-privilege template names both exact resources. Claude Sonnet
4.5 then achieved 3/3 valid direct AgentCore planning sessions and a hosted initial plan. The
hosted lifecycle stopped safely because that fixture did not make Grandma a real dependency.
The location-aware showcase now models explicit supervised transport, fixed synthetic travel
time, and driver availability. One bounded local Claude lifecycle produced a valid Grandma-based
Plan A, triggered grounded research after her decline, and reached deterministic approval and
`RESOLVED`. The public service remains `single + local` pending one final hosted lifecycle proof.
