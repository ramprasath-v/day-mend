# DayMend AWS Deployment

## Deployed demo

DayMend is deployed in AWS account `109837542034`, region `us-east-1`, with no credentials or
account keys stored in the repository.

| Surface | Deployed value |
| --- | --- |
| Frontend | <https://d28bm0qb8qheeh.cloudfront.net> |
| Backend | <https://5zvgskmgiu.us-east-1.awsapprunner.com> |
| Health | <https://5zvgskmgiu.us-east-1.awsapprunner.com/health> |
| Model | `amazon.nova-pro-v1:0` |
| DynamoDB table | `daymend-demo-recovery-cases` |
| ECR repository | `daymend-demo-backend` |
| CloudFormation stacks | `daymend-demo-foundation`, `daymend-demo-service` |
| CloudWatch application log | `/aws/apprunner/daymend-demo-api/2b1af8921aad451497c6e483a076017c/application` |

The public surface is an unauthenticated hackathon demo and accepts synthetic data only. Each
start action creates a new `RecoveryCase`; it never reuses a stale resolved aggregate.

## Architecture and deployment

`infra/foundation.yaml` creates the on-demand encrypted DynamoDB table, scan-on-push ECR
repository, versioned private S3 bucket, CloudFront origin access control, and HTTPS distribution.
`infra/service.yaml` creates App Runner and its narrowly scoped image-access and instance roles.
Both are CloudFormation; no second infrastructure framework is used.

`scripts/deploy-aws.sh` deploys the foundation, builds a single-platform `linux/amd64` image,
pushes an immutable timestamped ECR tag, deploys App Runner, builds Angular, writes the deployed
backend URL into the generated `config.js`, syncs the bundle to S3, and invalidates CloudFront.
The App Runner service uses a TCP platform health probe, while public `GET /health` remains a
lightweight application check that invokes neither Bedrock nor DynamoDB.

App Runner has a 120-second total HTTP request limit. The hosted proof remained within it:
browser initial planning was approximately 24 seconds, browser replanning approximately 51
seconds, and approval/execution/completion approximately 3.3 seconds. The final
observability-enabled API proof took approximately 13 seconds for initial planning and 24
seconds for a two-attempt replan. The bounded three-proposal cap remains unchanged.

## Production configuration and CORS

App Runner receives only non-secret environment configuration:

```text
AWS_REGION=us-east-1
DAYMEND_BEDROCK_MODEL_ID=amazon.nova-pro-v1:0
DAYMEND_RECOVERY_REPOSITORY=dynamodb
DAYMEND_RECOVERY_TABLE=daymend-demo-recovery-cases
DAYMEND_ALLOWED_ORIGINS=https://d28bm0qb8qheeh.cloudfront.net,http://localhost:4200,http://127.0.0.1:4200
```

The verified CORS response returns the exact CloudFront origin, not `*`. Angular production reads
the API base URL from the deployed `config.js`; development still uses `http://localhost:8000`.

## IAM boundary

The App Runner ECR access role can request an ECR authorization token and read layers only from
`daymend-demo-backend`. The application instance role can only:

- `dynamodb:GetItem` and `dynamodb:PutItem` on `daymend-demo-recovery-cases`; and
- `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream` on the regional
  `amazon.nova-pro-v1:0` foundation-model ARN.

App Runner's AWS-managed service-linked role publishes platform and application stdout/stderr to
CloudWatch. No `AdministratorAccess`, embedded credential, wildcard production CORS, or runtime
infrastructure-management permission is present in the templates. The identity running
CloudFormation needs separate deployment permissions; those are not granted to the application.

## Structured observability

`app.observability.log_event` accepts only reviewed fields and rejects arbitrary fields, so raw
prompts, family messages, credentials, tokens, and hidden reasoning cannot accidentally be added.
The application stream includes:

```text
recovery_started → planning_started → planning_attempt → planning_validated
→ caregiver_declined → assumption_invalidated → replanning_started
→ planning_attempt → replan_validated → approval_requested → approval_decision
→ execution_started → execution_action_completed → completion_verified
→ recovery_resolved
```

`recovery_failed` is emitted on model, bounded planning, execution, or completion failure paths.
Safe Bedrock events contain model ID, phase, latency, success, attempt count, and the five tool
names. Strands did not expose stable input/output token counts at this application boundary, so
token counts are intentionally not claimed or logged. App Runner's CloudWatch groups plus native
Bedrock metrics provide sufficient hackathon evidence without a custom dashboard.

The observability proof case `5a480dac-e97a-44db-a7dc-3c5c3de70b4f` recorded a successful
12,767 ms initial Nova Pro call using all five tools and a successful 23,529 ms two-attempt
replan. Attempt 1 was deterministically rejected with three issues; attempt 2 passed. The same
case then recorded approval, six successful simulated actions, deterministic completion, and
`RESOLVED` at version 6.

## Hosted browser proof

Browser case `e8cc73fe-6556-427c-a523-fb40151c3bfa` proved the judge-facing path:

1. CloudFront loaded the Angular status UI over HTTPS.
2. App Runner invoked the one Strands Recovery Agent and Nova Pro to create
   `recovery_plan_2`, a valid `$92` Plan A.
3. Grandma's decline invalidated three dependent assumptions and preserved five Plan A segments.
4. Nova produced valid `$114` Plan B `recovery_plan_4`.
5. Deterministic policy requested approval above the `$30` automatic-spend limit.
6. Approval `6a72e5a3-566c-4306-9be8-e2052f92ee99` resumed the same case.
7. Seven simulated calendar/caregiver actions succeeded.
8. Deterministic completion verification set `RESOLVED` at version 6.
9. A full page reload restored the same resolved case from DynamoDB.

These amounts describe this run only. Model output is not hardcoded, and later valid runs may
produce different costs or plan identifiers.

## AgentCore evaluation

**AGENTCORE EVALUATED — NOT DEPLOYED.** The appropriate component would be Amazon Bedrock
AgentCore Runtime, not Gateway: Runtime hosts a Strands agent and exposes the AgentCore
`/invocations` and `/ping` contract with session identity. The existing Recovery Agent can run
there in principle.

It is not a safe drop-in host for this milestone. `RecoveryApplicationService` currently owns
the bounded orchestration around multiple structured agent calls: request-local synthetic tool
context, deterministic validation feedback, world-state invalidation, DynamoDB persistence,
approval, execution, and completion. Moving only reasoning to AgentCore requires a new remote
planning gateway that serializes scenario/tool context, preserves the same conversation across
proposal repairs, maps structured results and failures, supplies AgentCore session IDs, and adds
`InvokeAgentRuntime` IAM/authentication, retries, and timeouts. Moving the entire FastAPI service
would incorrectly absorb deterministic business rules into the reasoning runtime and would not
provide the existing public REST routes.

That is a meaningful architectural split and failure-mode expansion, not deployment wrapping.
App Runner therefore hosts the unchanged FastAPI workflow and its in-process Strands/Bedrock
reasoning boundary. A future AgentCore adapter should implement the existing
`RecoveryPlanningGateway` protocol while `PlanValidator`, `ApprovalService`, and
`CompletionVerifier` remain in FastAPI. This preserves tools, structured output, the three-attempt
cap, replanning, and the same DynamoDB lifecycle before AgentCore is claimed as deployed.

Primary AWS references used for the decision:

- [AgentCore Runtime direct-code deployment](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-code-deploy-python.html)
- [How AgentCore Runtime works](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-how-it-works.html)
- [Custom AgentCore deployment contract](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/getting-started-custom.html)
- [App Runner runtime limits](https://docs.aws.amazon.com/apprunner/latest/dg/develop.html)
- [App Runner CloudWatch logs](https://docs.aws.amazon.com/apprunner/latest/dg/monitor-cwl.html)

## Operations

Validate and deploy:

```bash
aws cloudformation validate-template --region us-east-1 \
  --template-body file://infra/foundation.yaml
aws cloudformation validate-template --region us-east-1 \
  --template-body file://infra/service.yaml
AWS_REGION=us-east-1 ./scripts/deploy-aws.sh
```

Inspect health, service state, and logs:

```bash
curl https://5zvgskmgiu.us-east-1.awsapprunner.com/health
aws apprunner list-services --region us-east-1
aws logs tail \
  /aws/apprunner/daymend-demo-api/2b1af8921aad451497c6e483a076017c/application \
  --region us-east-1 --follow
```

The table, ECR repository, and frontend bucket use `Retain` policies to prevent accidental data
loss if a stack is deleted. Remove retained demo resources manually only when intentionally
decommissioning the hosted demo.

## Secret audit

The final working-tree and git-history scan checked AWS access-key IDs, AWS credential variable
names, session tokens, `sk-` tokens, generic API-key assignments, private-key blocks, tracked
`.env`/credential files, and private-key extensions. It found no real secret or tracked sensitive
file. The only matching file is the existing `backend/tests/test_api.py`, which deliberately uses
the literal fake value `do-not-expose` to prove exception details resembling a credential are
redacted from HTTP responses. That sentinel also exists in normal git history and requires no
history rewrite.
