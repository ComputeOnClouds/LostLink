#!/usr/bin/env bash
# Bootstrap (idempotent) then deploy the Auth stack.
set -euo pipefail
cd "$(dirname "$0")/../infra"

ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGION=$(aws configure get region)
echo "Bootstrapping CDK for aws://$ACCOUNT/$REGION ..."
npx cdk bootstrap "aws://$ACCOUNT/$REGION"

echo "Deploying LostLink-Auth ..."
npx cdk deploy LostLink-Auth --require-approval never
