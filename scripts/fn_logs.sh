#!/usr/bin/env bash
set -euo pipefail
REGION="${AWS_REGION:-ap-southeast-2}"
FN="${1:-LostLink-StaffFn}"
LOG="/aws/lambda/$FN"
START=$(( ($(date +%s) - 600) * 1000 ))
echo "Recent logs for $FN:"
aws logs filter-log-events --region "$REGION" --log-group-name "$LOG" \
  --start-time "$START" --query 'events[].message' --output text 2>&1 | tr '\t' '\n' | tail -40
