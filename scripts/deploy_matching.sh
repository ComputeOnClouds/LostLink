#!/usr/bin/env bash
# Deploy the matching pipeline: Data (adds SQS queue), Api (queue env), Matching (worker).
set -euo pipefail
cd "$(dirname "$0")/../infra"
npx cdk deploy LostLink-Data LostLink-Api LostLink-Matching --require-approval never
