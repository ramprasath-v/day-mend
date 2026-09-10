# DayMend AWS deployment

## Current hosted system

DayMend is deployed in `us-east-1`:

| Component | Current configuration |
| --- | --- |
| Frontend | Angular on private S3 behind CloudFront |
| Public URL | <https://d28bm0qb8qheeh.cloudfront.net/> |
| Backend | FastAPI on App Runner |
| Health URL | <https://5zvgskmgiu.us-east-1.awsapprunner.com/health> |
| Agent runtime | Amazon Bedrock AgentCore, deployed v12 |
| Agent architecture | `multi_research` (three Strands agents) |
| Model | `us.anthropic.claude-sonnet-4-5-20250929-v1:0` |
| Persistence | `daymend-demo-recovery-cases` DynamoDB table |
| Observability | App Runner and AgentCore logs in CloudWatch |

The public application is an unauthenticated hackathon demo using synthetic data.

## Request path

```text
CloudFront/S3
  → App Runner/FastAPI
  → RecoveryApplicationService
  → AgentCore Runtime v12
  → Recovery Orchestrator / Constraint Planner / Backup Care Research
  → Claude Sonnet 4.5 on Bedrock

FastAPI retains deterministic validation, policy, approval, execution,
completion verification, and DynamoDB persistence.
```

AgentCore uses Python 3.12. The App Runner backend container currently uses Python 3.11; these are
separate runtime environments.

## Production environment

The proven App Runner configuration is:

```bash
DAYMEND_AGENT_RUNTIME=agentcore
DAYMEND_AGENT_ARCHITECTURE=multi_research
DAYMEND_AGENTCORE_RUNTIME_ARN=arn:aws:bedrock-agentcore:us-east-1:109837542034:runtime/daymend_reasoning-nVUAuPG7rz
DAYMEND_BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-5-20250929-v1:0
DAYMEND_RECOVERY_REPOSITORY=dynamodb
DAYMEND_RECOVERY_TABLE=daymend-demo-recovery-cases
AWS_REGION=us-east-1
```

The AgentCore runtime environment uses the same model ID and
`DAYMEND_AGENT_ARCHITECTURE=multi_research`.

## Infrastructure

- `infra/foundation.yaml` defines ECR, DynamoDB, the private frontend bucket, and CloudFront.
- `infra/service.yaml` defines App Runner, its autoscaling configuration, and runtime IAM.
- `infra/agentcore.yaml` defines the direct-code AgentCore runtime and execution role.
- `scripts/deploy-agentcore.sh` packages the Python 3.12 runtime and updates its CloudFormation
  stack.
- `scripts/deploy-aws.sh` updates the foundation/service stacks, backend image, frontend bundle,
  runtime config, and CloudFront cache.

The scripts retain conservative development-compatible defaults. A production-compatible update
must pass the explicit current values:

```bash
AWS_REGION=us-east-1 \
DAYMEND_AGENT_RUNTIME=agentcore \
DAYMEND_AGENT_ARCHITECTURE=multi_research \
DAYMEND_AGENTCORE_RUNTIME_ARN=arn:aws:bedrock-agentcore:us-east-1:109837542034:runtime/daymend_reasoning-nVUAuPG7rz \
DAYMEND_BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-5-20250929-v1:0 \
./scripts/deploy-aws.sh
```

Do not run deployment commands merely to validate documentation or application behavior.

## IAM boundary

The App Runner instance role can read/write the recovery table and, when AgentCore is selected,
invoke exactly these runtime resources:

```text
arn:aws:bedrock-agentcore:us-east-1:109837542034:runtime/daymend_reasoning-nVUAuPG7rz
arn:aws:bedrock-agentcore:us-east-1:109837542034:runtime/daymend_reasoning-nVUAuPG7rz/runtime-endpoint/DEFAULT
```

The AgentCore execution role can:

- read its versioned S3 runtime artifact;
- invoke the Claude Sonnet 4.5 inference profile and its allowed destination models;
- use the required Marketplace subscription permissions for the Claude product;
- write runtime logs and metrics.

It does not receive DynamoDB lifecycle authority. Recovery state remains application-owned.

## Frontend runtime configuration

The tracked `frontend/public/config.js` is intentionally neutral:

```javascript
window.__DAYMEND_CONFIG__ = window.__DAYMEND_CONFIG__ || { apiBaseUrl: '' };
```

The deployment path writes the App Runner URL only into the generated production artifact before
uploading it to S3. Development continues to use `http://localhost:8000`. After a frontend upload,
verify both the S3 object and the CloudFront response before testing the public UI.

## Persistence

The DynamoDB table uses `recovery_case_id` as its string partition key with on-demand billing. One
item stores the complete versioned Pydantic aggregate. Conditional writes reject stale versions.
The repository does not store credentials, prompts, or chain-of-thought.

## Progress and logs

Mutation requests carry `X-DayMend-Progress-ID`. App Runner serves:

- `GET /progress/{progress_id}/stream` as `text/event-stream` with buffering disabled;
- `GET /progress/{progress_id}` as a reconnect snapshot;
- `GET /recoveries/{recovery_case_id}/progress` for an existing case.

CloudWatch receives safe fields such as operation, request/case IDs, Planner attempts, validator
issue codes, role invocation counts, cost, approval, action results, and duration. Raw prompts,
reasoning, credentials, and complete request payloads are excluded.

## Rollback readiness

The preserved application fallback configuration is:

```bash
DAYMEND_AGENT_RUNTIME=local
DAYMEND_AGENT_ARCHITECTURE=single
```

Rollback changes App Runner configuration only; it does not delete the AgentCore runtime or
DynamoDB cases. The current proven production configuration remains AgentCore plus
`multi_research` and Claude Sonnet 4.5.

## Verification baseline

The final hosted proof established:

- App Runner healthy and AgentCore v12 `READY`;
- Plan A valid on the first Planner attempt in about 32.0 seconds server-side;
- Plan B valid on the first Planner attempt in about 60.5 seconds;
- one Backup Care Research invocation;
- deterministic `$87.75` cost and approval above the `$30` threshold;
- two successful simulated actions;
- deterministic completion and `RESOLVED`;
- DynamoDB reload of the same case;
- healthy SSE and no browser console errors.

Provider inventory and all execution integrations are synthetic. DayMend does not connect to a
real care marketplace, booking, payment, calendar, or messaging service.
