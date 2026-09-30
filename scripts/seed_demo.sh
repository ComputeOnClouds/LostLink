#!/usr/bin/env bash
# One-command demo seed: creates all demo users (individual + staff, two orgs) with
# confirmed passwords, ready for a walkthrough on the deployed app.
#
# Users created:
#   user@lostlink.example   / User!Pass123    (Individual)
#   user2@lostlink.example  / User2!Pass123   (Individual)
#   staff@lostlink.example  / Staff!Pass123    (Staff, org-nus)
#   staff2@lostlink.example / Staff2!Pass123   (Staff, org-other)
#
# Optionally set DEMO_EMAIL=you@domain to also create an Individual whose email is a real
# (SES-verified) address, so match emails actually arrive during the demo.
set -euo pipefail
REGION="${AWS_REGION:-ap-southeast-2}"
POOL="$(aws cloudformation describe-stacks --region "$REGION" --stack-name LostLink-Auth \
  --query "Stacks[0].Outputs[?ExportName=='LostLink-UserPoolId'].OutputValue" --output text)"

mk() { # email password group [org]
  local email="$1" pw="$2" group="$3" org="${4:-}"
  local attrs="Name=email,Value=$email Name=email_verified,Value=true"
  [ -n "$org" ] && attrs="$attrs Name=custom:organisationId,Value=$org"
  # shellcheck disable=SC2086
  aws cognito-idp admin-create-user --region "$REGION" --user-pool-id "$POOL" \
    --username "$email" --message-action SUPPRESS --user-attributes $attrs >/dev/null 2>&1 \
    || echo "  ($email exists, updating)"
  aws cognito-idp admin-set-user-password --region "$REGION" --user-pool-id "$POOL" \
    --username "$email" --password "$pw" --permanent >/dev/null
  [ -n "$org" ] && aws cognito-idp admin-update-user-attributes --region "$REGION" \
    --user-pool-id "$POOL" --username "$email" \
    --user-attributes Name=custom:organisationId,Value="$org" >/dev/null
  aws cognito-idp admin-add-user-to-group --region "$REGION" --user-pool-id "$POOL" \
    --username "$email" --group-name "$group" >/dev/null
  echo "  seeded $group: $email${org:+ ($org)}"
}

echo "Seeding demo users into $POOL ($REGION)..."
mk user@lostlink.example   'User!Pass123'   Individual
mk user2@lostlink.example  'User2!Pass123'  Individual
mk staff@lostlink.example  'Staff!Pass123'  Staff org-nus
mk staff2@lostlink.example 'Staff2!Pass123' Staff org-other
if [ -n "${DEMO_EMAIL:-}" ]; then
  mk "$DEMO_EMAIL" "${DEMO_PASSWORD:-Demo!Pass123}" Individual
  echo "  (real-email demo user: $DEMO_EMAIL — must be SES-verified to receive)"
fi
echo "Done. Open the app (LostLink-CloudFrontUrl) and sign in."
