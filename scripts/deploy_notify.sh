#!/usr/bin/env bash
# Deploy Notification + Api (owner_email) + Matching (SES sender/env).
# SENDER_EMAIL defaults to the verified NUS address; override to use another verified id.
set -euo pipefail
export SENDER_EMAIL="${SENDER_EMAIL:-satpathy.amrit@u.nus.edu}"
echo "Deploying with SENDER_EMAIL=$SENDER_EMAIL"
cd "$(dirname "$0")/../infra"
npx cdk deploy LostLink-Notification LostLink-Api LostLink-Matching --require-approval never
