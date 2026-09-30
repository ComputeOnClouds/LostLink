#!/usr/bin/env bash
# Task 6 smoke test: CloudFront serves the app, config.json is correct, bundle loads,
# and the config points at a working Cognito login (USER_PASSWORD, same flow the SPA uses).
set -euo pipefail
cd "$(dirname "$0")/.."

REGION="${AWS_REGION:-ap-southeast-2}"
cfn_out() {
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$1" \
    --query "Stacks[0].Outputs[?ExportName=='$2'].OutputValue" --output text
}

URL="$(cfn_out LostLink-Frontend LostLink-CloudFrontUrl)"
CLIENT_ID="$(cfn_out LostLink-Auth LostLink-UserPoolClientId)"
echo "CloudFront: $URL"

fail=0
ck() { if [ "$1" = "1" ]; then echo "  [OK  ] $2"; else echo "  [FAIL] $2"; fail=1; fi; }

echo "1. index.html served"
body=$(curl -fsSL "$URL/" || true)
echo "$body" | grep -qi "LostLink" && ck 1 "index.html contains app title" || ck 0 "index.html contains app title"
echo "$body" | grep -qiE "src=\"/assets/index-.*\.js\"" && ck 1 "index.html references JS bundle" || ck 0 "index.html references JS bundle"

echo "2. config.json served with expected keys"
cfg=$(curl -fsSL "$URL/config.json" || true)
echo "$cfg" | python3 -c "import sys,json;c=json.load(sys.stdin);assert c['apiUrl'].startswith('https://');assert c['userPoolId'];assert c['userPoolClientId'];assert c['region']=='$REGION';print('    config:',c['apiUrl'],c['region'])" && ck 1 "config.json valid + apiUrl/pool/client/region present" || ck 0 "config.json valid"

echo "3. JS bundle downloads"
asset=$(echo "$body" | grep -oE '/assets/index-[^\"]+\.js' | head -1)
curl -fsSL "$URL$asset" -o /dev/null && ck 1 "JS bundle $asset downloads" || ck 0 "JS bundle downloads"

echo "4. config points at a working login (individual + staff)"
login() {
  aws cognito-idp initiate-auth --region "$REGION" --auth-flow USER_PASSWORD_AUTH \
    --client-id "$CLIENT_ID" --auth-parameters USERNAME="$1",PASSWORD="$2" \
    --query 'AuthenticationResult.IdToken' --output text 2>/dev/null
}
tok=$(login user@lostlink.example 'User!Pass123'); [ -n "$tok" ] && [ "$tok" != "None" ] && ck 1 "individual login via SPA client works" || ck 0 "individual login works"
tok=$(login staff@lostlink.example 'Staff!Pass123'); [ -n "$tok" ] && [ "$tok" != "None" ] && ck 1 "staff login via SPA client works" || ck 0 "staff login works"

echo
if [ "$fail" = "0" ]; then echo "RESULT: all checks passed"; else echo "RESULT: FAILED"; exit 1; fi
