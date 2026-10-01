#!/usr/bin/env bash
# End-to-end check of self-service registration:
#   public SignUp -> confirm -> post-confirmation trigger adds Individual group
#   -> USER_PASSWORD_AUTH login -> ID token carries cognito:groups=[Individual], no org.
# Uses admin-confirm-sign-up as a test shortcut (SES sandbox won't email a code to an
# arbitrary throwaway address). Cleans up the test user at the end.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
export AWS_PAGER=""   # disable the interactive pager (stalls non-tty output)
REGION="${AWS_REGION:-ap-southeast-2}"
cfn_out() {
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$1" \
    --query "Stacks[0].Outputs[?ExportName=='$2'].OutputValue" --output text
}
POOL_ID="$(cfn_out LostLink-Auth LostLink-UserPoolId)"
CLIENT_ID="$(cfn_out LostLink-Auth LostLink-UserPoolClientId)"

STAMP="$(date +%s)"
EMAIL="selftest+${STAMP}@lostlink.example"
PASSWORD="SelfTest!Pass123"

cleanup() {
  aws cognito-idp admin-delete-user --region "$REGION" \
    --user-pool-id "$POOL_ID" --username "$EMAIL" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "pool=$POOL_ID client=$CLIENT_ID"
echo "test user=$EMAIL"

echo
echo "1) public SignUp (as the browser would) ..."
aws cognito-idp sign-up --region "$REGION" --client-id "$CLIENT_ID" \
  --username "$EMAIL" --password "$PASSWORD" \
  --user-attributes Name=email,Value="$EMAIL" >/dev/null
echo "   signed up (UNCONFIRMED)."

echo
echo "2) confirm (test shortcut; real users use the emailed code) ..."
aws cognito-idp admin-confirm-sign-up --region "$REGION" \
  --user-pool-id "$POOL_ID" --username "$EMAIL" >/dev/null
echo "   confirmed -> post-confirmation trigger should have run."

echo
echo "3) groups for the user (expect: Individual) ..."
sleep 5
GROUPS_JSON="$(aws cognito-idp admin-list-groups-for-user --region "$REGION" \
  --user-pool-id "$POOL_ID" --username "$EMAIL" --output json)"
echo "$GROUPS_JSON" | grep -q '"GroupName": "Individual"' \
  && echo "   OK: trigger assigned the Individual group" \
  || { echo "   FAIL: Individual group not assigned"; echo "$GROUPS_JSON"; exit 1; }

echo
echo "4) login via USER_PASSWORD_AUTH + decode ID token claims ..."
ID_TOKEN="$(aws cognito-idp initiate-auth --region "$REGION" \
  --auth-flow USER_PASSWORD_AUTH --client-id "$CLIENT_ID" \
  --auth-parameters USERNAME="$EMAIL",PASSWORD="$PASSWORD" \
  --query 'AuthenticationResult.IdToken' --output text)"
if [ -z "$ID_TOKEN" ] || [ "$ID_TOKEN" = "None" ]; then
  echo "   FAIL: login failed"; exit 1
fi
PAYLOAD="$(echo "$ID_TOKEN" | cut -d. -f2 | tr '_-' '/+')"
while [ $(( ${#PAYLOAD} % 4 )) -ne 0 ]; do PAYLOAD="$PAYLOAD="; done
echo "$PAYLOAD" | base64 -d 2>/dev/null | python3 -c "
import sys, json
c = json.load(sys.stdin)
groups = c.get('cognito:groups')
org = c.get('custom:organisationId')
print('   token groups =', groups)
print('   token org    =', org)
assert groups and 'Individual' in groups, 'Individual not in token groups'
assert not org, 'unexpected organisationId on a self-registered individual'
print('   OK: token carries Individual, no organisation -> routes to Individual portal')
"

echo
echo "ALL CHECKS PASSED — self-service registration works end to end."
