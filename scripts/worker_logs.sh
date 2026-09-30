#!/usr/bin/env bash
set -euo pipefail
REGION="${AWS_REGION:-ap-southeast-2}"
LOG="/aws/lambda/LostLink-MatchWorker"
# Look back 20 minutes across all streams.
START=$(( ($(date +%s) - 1200) * 1000 ))
aws logs filter-log-events --region "$REGION" --log-group-name "$LOG" \
  --start-time "$START" --query 'events[].message' --output text 2>&1 | tr '\t' '\n' | tail -60
