#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
cd "$(dirname "$0")/../infra"
npx cdk deploy LostLink-Auth --require-approval never
