#!/usr/bin/env bash
set -euo pipefail
REGION="${AWS_REGION:-ap-southeast-2}"
echo "SESv2 identities in $REGION:"
aws sesv2 list-email-identities --region "$REGION" \
  --query "EmailIdentities[].[IdentityName,VerifiedForSendingStatus]" --output text 2>&1 || echo "none / error"
echo "--- send quota (Max24Hour>1 usually means production, 200 = sandbox-ish):"
aws sesv2 get-account --region "$REGION" \
  --query "{Prod:ProductionAccessEnabled,SendQuota:SendQuota}" --output json 2>&1 || echo "get-account failed"
