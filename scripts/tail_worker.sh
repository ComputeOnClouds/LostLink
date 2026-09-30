#!/usr/bin/env bash
set -euo pipefail
REGION="${AWS_REGION:-ap-southeast-2}"
START=$(( ($(date +%s) - 600) * 1000 ))
aws logs filter-log-events --region "$REGION" \
  --log-group-name /aws/lambda/LostLink-MatchWorker \
  --start-time "$START" --query 'events[].message' --output text 2>&1 \
  | tr '\t' '\n' | grep -iE 'error|exception|traceback|describe|claude|bedrock|could not|denied|no text' | tail -30
