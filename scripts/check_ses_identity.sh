#!/usr/bin/env bash
set -euo pipefail
REGION="${AWS_REGION:-ap-southeast-2}"
EMAIL="${1:-satpathy.amrit@u.nus.edu}"
echo "Identity: $EMAIL"
aws sesv2 get-email-identity --region "$REGION" --email-identity "$EMAIL" \
  --query '{Verified:VerifiedForSendingStatus, Type:IdentityType}' --output json
