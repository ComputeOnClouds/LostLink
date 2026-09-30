#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../infra"
echo "Deploying LostLink-Api ..."
npx cdk deploy LostLink-Api --require-approval never
