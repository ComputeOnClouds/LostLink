#!/usr/bin/env bash
#
# Task 2 seed + verification for the Cognito AuthStack.
#
# Creates one Staff user (bound to an organisation via custom:organisationId) and one
# Individual user, using the Cognito admin APIs so no email round-trip is needed for
# seeding. Then signs each in and prints the decoded ID-token claims so you can confirm
# the group + organisationId claims are present.
#
# Requires: AWS CLI configured with credentials for the account/region where
# LostLink-Auth is deployed. Region defaults to ap-southeast-1.
#
# Usage:
#   bash scripts/seed_auth.sh
# Optional env overrides:
#   REGION, STAFF_EMAIL, STAFF_PASSWORD, INDIVIDUAL_EMAIL, INDIVIDUAL_PASSWORD, ORG_ID
set -euo pipefail

REGION="${REGION:-ap-southeast-2}"
STACK="LostLink-Auth"

STAFF_EMAIL="${STAFF_EMAIL:-staff@lostlink.example}"
STAFF_PASSWORD="${STAFF_PASSWORD:-Staff!Pass123}"
INDIVIDUAL_EMAIL="${INDIVIDUAL_EMAIL:-user@lostlink.example}"
INDIVIDUAL_PASSWORD="${INDIVIDUAL_PASSWORD:-User!Pass123}"
ORG_ID="${ORG_ID:-org-nus}"

command -v aws >/dev/null 2>&1 || { echo "ERROR: AWS CLI not found. Install it and run 'aws configure'."; exit 1; }

echo "Reading pool/client ids from CloudFormation outputs of $STACK ($REGION)..."
POOL_ID=$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?ExportName=='LostLink-UserPoolId'].OutputValue" --output text)
CLIENT_ID=$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?ExportName=='LostLink-UserPoolClientId'].OutputValue" --output text)

if [ -z "$POOL_ID" ] || [ "$POOL_ID" = "None" ]; then
  echo "ERROR: could not read UserPoolId. Is $STACK deployed?"; exit 1
fi
echo "  UserPoolId=$POOL_ID"
echo "  ClientId=$CLIENT_ID"

# ---- helper: create (or reset) a confirmed user, set password, add to group --------
seed_user() {
  local email="$1" password="$2" group="$3" org="$4"

  echo
  echo "Seeding $group user: $email"

  # Create the user without sending an invite email. Ignore error if already exists.
  local attrs="Name=email,Value=$email Name=email_verified,Value=true"
  if [ -n "$org" ]; then
    attrs="$attrs Name=custom:organisationId,Value=$org"
  fi
  # shellcheck disable=SC2086
  aws cognito-idp admin-create-user --region "$REGION" \
    --user-pool-id "$POOL_ID" --username "$email" \
    --message-action SUPPRESS \
    --user-attributes $attrs >/dev/null 2>&1 || echo "  (user may already exist — continuing)"

  # Set a permanent password so we can sign in immediately.
  aws cognito-idp admin-set-user-password --region "$REGION" \
    --user-pool-id "$POOL_ID" --username "$email" \
    --password "$password" --permanent >/dev/null

  # Ensure the org attribute is set even if the user pre-existed.
  if [ -n "$org" ]; then
    aws cognito-idp admin-update-user-attributes --region "$REGION" \
      --user-pool-id "$POOL_ID" --username "$email" \
      --user-attributes Name=custom:organisationId,Value="$org" >/dev/null
  fi

  aws cognito-idp admin-add-user-to-group --region "$REGION" \
    --user-pool-id "$POOL_ID" --username "$email" --group-name "$group" >/dev/null
  echo "  created + confirmed, added to group '$group'${org:+, org=$org}"
}

# ---- helper: sign in and decode the ID token claims --------------------------------
verify_login() {
  local email="$1" password="$2" expect_group="$3" expect_org="$4"

  echo
  echo "Verifying login for $email ..."
  local id_token
  id_token=$(aws cognito-idp initiate-auth --region "$REGION" \
    --auth-flow USER_PASSWORD_AUTH --client-id "$CLIENT_ID" \
    --auth-parameters USERNAME="$email",PASSWORD="$password" \
    --query 'AuthenticationResult.IdToken' --output text)

  if [ -z "$id_token" ] || [ "$id_token" = "None" ]; then
    echo "  ERROR: login failed"; return 1
  fi

  # Decode the JWT payload (2nd segment), base64url -> json.
  local payload
  payload=$(echo "$id_token" | cut -d. -f2 | tr '_-' '/+')
  # pad to a multiple of 4 for base64
  while [ $(( ${#payload} % 4 )) -ne 0 ]; do payload="$payload="; done
  local claims
  claims=$(echo "$payload" | base64 -d 2>/dev/null)

  echo "  claims: cognito:groups + custom:organisationId ->"
  echo "$claims" | python3 -c "import sys,json; c=json.load(sys.stdin); print('    groups =', c.get('cognito:groups')); print('    org    =', c.get('custom:organisationId'))"

  echo "$claims" | grep -q "\"$expect_group\"" && echo "  OK: group '$expect_group' present" || { echo "  FAIL: expected group '$expect_group'"; return 1; }
  if [ -n "$expect_org" ]; then
    echo "$claims" | grep -q "$expect_org" && echo "  OK: org '$expect_org' present" || { echo "  FAIL: expected org '$expect_org'"; return 1; }
  fi
}

seed_user "$STAFF_EMAIL" "$STAFF_PASSWORD" "Staff" "$ORG_ID"
seed_user "$INDIVIDUAL_EMAIL" "$INDIVIDUAL_PASSWORD" "Individual" ""

verify_login "$STAFF_EMAIL" "$STAFF_PASSWORD" "Staff" "$ORG_ID"
verify_login "$INDIVIDUAL_EMAIL" "$INDIVIDUAL_PASSWORD" "Individual" ""

echo
echo "Seed + verification complete."
