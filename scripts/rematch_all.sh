#!/usr/bin/env bash
# Purge the stale DLQ, then re-enqueue a match job for every current item so the worker
# recomputes statuses (pending_match -> matched/no_match) under the latest logic.
set -euo pipefail
REGION="${AWS_REGION:-ap-southeast-2}"
cfn_out() {
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$1" \
    --query "Stacks[0].Outputs[?ExportName=='$2'].OutputValue" --output text
}
QURL=$(cfn_out LostLink-Data LostLink-MatchQueueUrl)
ITEMS=$(cfn_out LostLink-Data LostLink-ItemsTableName)

DLQ=$(aws sqs list-queues --region "$REGION" --queue-name-prefix LostLink-match-dlq \
  --query 'QueueUrls[0]' --output text 2>/dev/null || echo None)
if [ "$DLQ" != "None" ] && [ -n "$DLQ" ]; then
  echo "Purging stale DLQ..."
  aws sqs purge-queue --region "$REGION" --queue-url "$DLQ" >/dev/null || true
fi

echo "Re-enqueuing match jobs for all current items..."
# itemId + itemType pairs
PAIRS=$(aws dynamodb scan --region "$REGION" --table-name "$ITEMS" \
  --projection-expression "itemId,itemType" \
  --query "Items[].[itemId.S, itemType.S]" --output text)
n=0
while read -r id type; do
  [ -z "${id:-}" ] && continue
  aws sqs send-message --region "$REGION" --queue-url "$QURL" \
    --message-body "{\"itemId\":\"$id\",\"type\":\"$type\"}" >/dev/null
  n=$((n+1))
done <<< "$PAIRS"
echo "enqueued $n jobs"
echo "Waiting 20s for the worker to process..."
sleep 20
