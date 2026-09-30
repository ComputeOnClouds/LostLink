#!/usr/bin/env bash
# Show recent matching-worker log events, and flag any Bedrock/Claude errors.
set -euo pipefail
REGION="${AWS_REGION:-ap-southeast-2}"
LOG="/aws/lambda/LostLink-MatchWorker"
echo "Recent worker logs ($LOG):"
STREAM=$(aws logs describe-log-streams --region "$REGION" --log-group-name "$LOG" \
  --order-by LastEventTime --descending --max-items 1 \
  --query 'logStreams[0].logStreamName' --output text 2>/dev/null || echo "")
if [ -z "$STREAM" ] || [ "$STREAM" = "None" ]; then
  echo "  (no log streams yet)"; exit 0
fi
aws logs get-log-events --region "$REGION" --log-group-name "$LOG" \
  --log-stream-name "$STREAM" --limit 40 \
  --query 'events[].message' --output text 2>/dev/null | tail -40
