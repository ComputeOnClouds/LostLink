#!/usr/bin/env bash
# Build the app, update Data (drops the old frontend bucket), then deploy Frontend.
set -euo pipefail
cd "$(dirname "$0")/.."

bash scripts/build_frontend.sh

cd infra
echo "Updating LostLink-Data (removes frontend bucket, now owned by FrontendStack) ..."
npx cdk deploy LostLink-Data --require-approval never
echo "Deploying LostLink-Frontend ..."
npx cdk deploy LostLink-Frontend --require-approval never
