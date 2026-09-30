#!/usr/bin/env bash
# One-time repo init + first commit for LostLink. Stages the whole project
# (.gitignore excludes node_modules/cdk.out/.venv/dist/secrets).
set -euo pipefail
cd "$(dirname "$0")/.."

git init
git add .
git commit -m "Initial commit: LostLink privacy-aware cross-organisation Lost & Found SaaS (AWS CDK + Lambda + React)"
git branch -M main
echo "--- staged file count:"
git ls-files | wc -l
echo "--- sanity: any node_modules/venv/cdk.out tracked? (should be empty)"
git ls-files | grep -E 'node_modules|\.venv|cdk\.out|/dist/' || echo "none (good)"
