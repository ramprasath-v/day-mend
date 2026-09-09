#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AWS_REGION="${AWS_REGION:-us-east-1}"
RESOURCE_PREFIX="${DAYMEND_RESOURCE_PREFIX:-daymend-demo}"
STACK_NAME="${RESOURCE_PREFIX}-agentcore"
MODEL_ID="${DAYMEND_BEDROCK_MODEL_ID:-amazon.nova-pro-v1:0}"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
ARTIFACT_BUCKET="${RESOURCE_PREFIX}-agentcore-artifacts-${ACCOUNT_ID}-${AWS_REGION}"
ARTIFACT_KEY="runtime/daymend-agentcore-$(date -u +%Y%m%d%H%M%S).zip"
PACKAGE_DIR="$(mktemp -d)"
PACKAGE_ZIP="$(mktemp -t daymend-agentcore).zip"
trap 'rm -rf "$PACKAGE_DIR" "$PACKAGE_ZIP"' EXIT

if ! aws s3api head-bucket --bucket "$ARTIFACT_BUCKET" 2>/dev/null; then
  if [ "$AWS_REGION" = "us-east-1" ]; then
    aws s3api create-bucket \
      --bucket "$ARTIFACT_BUCKET" \
      --region "$AWS_REGION"
  else
    aws s3api create-bucket \
      --bucket "$ARTIFACT_BUCKET" \
      --region "$AWS_REGION" \
      --create-bucket-configuration "LocationConstraint=$AWS_REGION"
  fi

  aws s3api put-bucket-encryption \
    --bucket "$ARTIFACT_BUCKET" \
    --server-side-encryption-configuration \
      '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

  aws s3api put-public-access-block \
    --bucket "$ARTIFACT_BUCKET" \
    --public-access-block-configuration \
      BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

  aws s3api put-bucket-versioning \
    --bucket "$ARTIFACT_BUCKET" \
    --versioning-configuration Status=Enabled
fi

python3 -m pip install \
  --platform manylinux2014_aarch64 \
  --implementation cp \
  --python-version 3.12 \
  --abi cp312 \
  --only-binary=:all: \
  --no-compile \
  --target "$PACKAGE_DIR" \
  -r "$PROJECT_ROOT/backend/requirements-agentcore.txt"

cp -R "$PROJECT_ROOT/backend/app" "$PACKAGE_DIR/app"
find "$PACKAGE_DIR" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$PACKAGE_DIR" -type f -name '*.pyc' -delete
find "$PACKAGE_DIR" -type f -name '*.pyo' -delete

cp "$PROJECT_ROOT/backend/agentcore_runtime.py" "$PACKAGE_DIR/agentcore_runtime.py"
(cd "$PACKAGE_DIR" && zip -qr "$PACKAGE_ZIP" .)
aws s3 cp "$PACKAGE_ZIP" "s3://${ARTIFACT_BUCKET}/${ARTIFACT_KEY}" --region "$AWS_REGION"

aws cloudformation deploy \
  --region "$AWS_REGION" \
  --stack-name "$STACK_NAME" \
  --template-file "$PROJECT_ROOT/infra/agentcore.yaml" \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    "ResourcePrefix=$RESOURCE_PREFIX" \
    "ArtifactBucket=$ARTIFACT_BUCKET" \
    "ArtifactKey=$ARTIFACT_KEY" \
    "BedrockModelId=$MODEL_ID"

aws cloudformation describe-stacks \
  --region "$AWS_REGION" \
  --stack-name "$STACK_NAME" \
  --query 'Stacks[0].Outputs' \
  --output table
