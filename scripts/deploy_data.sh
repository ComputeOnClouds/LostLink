#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../infra"
echo "Deploying LostLink-Data ..."
npx cdk deploy LostLink-Data --require-approval never
