#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AWS_REGION="${AWS_REGION:-us-east-1}"
RESOURCE_PREFIX="${DAYMEND_RESOURCE_PREFIX:-daymend-demo}"
FOUNDATION_STACK="${RESOURCE_PREFIX}-foundation"
SERVICE_STACK="${RESOURCE_PREFIX}-service"
MODEL_ID="${DAYMEND_BEDROCK_MODEL_ID:-amazon.nova-pro-v1:0}"
AGENT_ARCHITECTURE="${DAYMEND_AGENT_ARCHITECTURE:-single}"
AGENT_RUNTIME="${DAYMEND_AGENT_RUNTIME:-local}"
AGENTCORE_RUNTIME_ARN="${DAYMEND_AGENTCORE_RUNTIME_ARN:-}"
IMAGE_TAG="$(date -u +%Y%m%d%H%M%S)"

if [[ "$AGENT_RUNTIME" == "agentcore" && -z "$AGENTCORE_RUNTIME_ARN" ]]; then
  echo "DAYMEND_AGENTCORE_RUNTIME_ARN is required when DAYMEND_AGENT_RUNTIME=agentcore" >&2
  exit 2
fi

stack_output() {
  aws cloudformation describe-stacks \
    --region "$AWS_REGION" \
    --stack-name "$1" \
    --query "Stacks[0].Outputs[?OutputKey=='$2'].OutputValue" \
    --output text
}

aws cloudformation deploy \
  --region "$AWS_REGION" \
  --stack-name "$FOUNDATION_STACK" \
  --template-file "$PROJECT_ROOT/infra/foundation.yaml" \
  --parameter-overrides "ResourcePrefix=$RESOURCE_PREFIX"

REPOSITORY_URI="$(stack_output "$FOUNDATION_STACK" BackendRepositoryUri)"
TABLE_NAME="$(stack_output "$FOUNDATION_STACK" RecoveryCasesTableName)"
FRONTEND_BUCKET="$(stack_output "$FOUNDATION_STACK" FrontendBucketName)"
DISTRIBUTION_ID="$(stack_output "$FOUNDATION_STACK" FrontendDistributionId)"
FRONTEND_DOMAIN="$(stack_output "$FOUNDATION_STACK" FrontendDomainName)"
IMAGE_IDENTIFIER="${REPOSITORY_URI}:${IMAGE_TAG}"

aws ecr get-login-password --region "$AWS_REGION" |
  docker login --username AWS --password-stdin "${REPOSITORY_URI%%/*}"
docker buildx build \
  --platform linux/amd64 \
  --provenance=false \
  --push \
  --tag "$IMAGE_IDENTIFIER" \
  "$PROJECT_ROOT/backend"

aws cloudformation deploy \
  --region "$AWS_REGION" \
  --stack-name "$SERVICE_STACK" \
  --template-file "$PROJECT_ROOT/infra/service.yaml" \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    "ResourcePrefix=$RESOURCE_PREFIX" \
    "ImageIdentifier=$IMAGE_IDENTIFIER" \
    "RecoveryCasesTableName=$TABLE_NAME" \
    "FrontendOrigin=https://$FRONTEND_DOMAIN" \
    "BedrockModelId=$MODEL_ID" \
    "AgentArchitecture=$AGENT_ARCHITECTURE" \
    "AgentRuntime=$AGENT_RUNTIME" \
    "AgentCoreRuntimeArn=$AGENTCORE_RUNTIME_ARN"

BACKEND_URL="$(stack_output "$SERVICE_STACK" BackendServiceUrl)"

npm --prefix "$PROJECT_ROOT/frontend" ci
npm --prefix "$PROJECT_ROOT/frontend" run build
printf 'window.__DAYMEND_CONFIG__ = {"apiBaseUrl":"%s"};\n' "$BACKEND_URL" \
  > "$PROJECT_ROOT/frontend/dist/frontend/browser/config.js"
aws s3 sync \
  "$PROJECT_ROOT/frontend/dist/frontend/browser" \
  "s3://$FRONTEND_BUCKET" \
  --delete \
  --region "$AWS_REGION"
INVALIDATION_ID="$(aws cloudfront create-invalidation \
  --distribution-id "$DISTRIBUTION_ID" \
  --paths '/*' \
  --query 'Invalidation.Id' \
  --output text)"
aws cloudfront wait invalidation-completed \
  --distribution-id "$DISTRIBUTION_ID" \
  --id "$INVALIDATION_ID"

printf 'Frontend URL: https://%s\n' "$FRONTEND_DOMAIN"
printf 'Backend URL: %s\n' "$BACKEND_URL"
printf 'DynamoDB table: %s\n' "$TABLE_NAME"
printf 'App Runner image: %s\n' "$IMAGE_IDENTIFIER"
printf 'Agent architecture: %s\n' "$AGENT_ARCHITECTURE"
printf 'Agent runtime: %s\n' "$AGENT_RUNTIME"
