#!/usr/bin/env bash
set -euo pipefail
REGION="${AWS_REGION:-ap-southeast-2}"
for s in LostLink-Auth LostLink-Data LostLink-Api LostLink-Matching LostLink-Notification LostLink-Frontend; do
  st=$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$s" \
        --query 'Stacks[0].StackStatus' --output text 2>/dev/null || echo "NOT_DEPLOYED")
  printf '%-24s %s\n' "$s" "$st"
done
