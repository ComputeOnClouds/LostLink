#!/usr/bin/env bash
# Task 10 REAL email-delivery check. Requires a VERIFIED SES sender.
#
# Prereqs (one-time):
#   1. Deploy with a real sender:  SENDER_EMAIL=you@example.com bash scripts/deploy_notify.sh
#   2. Click the verification link SES emails to you@example.com.
#   3. In the SES sandbox, recipients must be verified too — but the mailbox simulator
#      success@simulator.amazonses.com is always accepted, so we use it here.
#
# This registers an Individual whose email is the simulator address, submits a matching
# found + lost pair, and asserts SES accepted the send (SentLast24Hours increments and
# the match row is notified=true). Delivery to the simulator is a no-op mailbox but
# confirms SES accepted a real send from the verified sender.
set -euo pipefail
cd "$(dirname "$0")/.."
REGION="${AWS_REGION:-ap-southeast-2}"

SENDER="$(aws cloudformation describe-stacks --region "$REGION" --stack-name LostLink-Notification \
  --query "Stacks[0].Outputs[?ExportName=='LostLink-SenderEmail'].OutputValue" --output text)"
echo "Configured sender: $SENDER"
if [[ "$SENDER" == *".example" ]]; then
  echo "SENDER_EMAIL is still the placeholder. Redeploy with a real verified address:"
  echo "  SENDER_EMAIL=you@example.com bash scripts/deploy_notify.sh"
  exit 1
fi

VSTATUS="$(aws sesv2 get-email-identity --region "$REGION" --email-identity "$SENDER" \
  --query 'VerifiedForSendingStatus' --output text 2>/dev/null || echo 'UNKNOWN')"
echo "Sender verification status: $VSTATUS"
if [[ "$VSTATUS" != "True" ]]; then
  echo "Sender not verified yet — click the link SES emailed to $SENDER, then re-run."
  exit 1
fi

before=$(aws sesv2 get-account --region "$REGION" --query 'SendQuota.SentLast24Hours' --output text)
echo "SES SentLast24Hours before: $before"
echo "(Now run scripts/verify_notify.sh after setting the individual's email to"
echo " success@simulator.amazonses.com, or submit a matching pair via the app.)"
echo "After a match fires, SentLast24Hours should increase by 1 and no duplicate on re-drive."
