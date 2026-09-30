#!/usr/bin/env bash
# Task 4 integration test runner: resolves stack outputs, then runs the reports API test.
set -euo pipefail
cd "$(dirname "$0")/.."

REGION="${AWS_REGION:-ap-southeast-2}"

cfn_out() {
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$1" \
    --query "Stacks[0].Outputs[?ExportName=='$2'].OutputValue" --output text
}

export REGION
export API_URL="$(cfn_out LostLink-Api LostLink-ApiUrl)"
export USER_POOL_ID="$(cfn_out LostLink-Auth LostLink-UserPoolId)"
export CLIENT_ID="$(cfn_out LostLink-Auth LostLink-UserPoolClientId)"
export ITEMS_TABLE="$(cfn_out LostLink-Data LostLink-ItemsTableName)"
export PHOTOS_BUCKET="$(cfn_out LostLink-Data LostLink-PhotosBucketName)"

echo "API_URL=$API_URL"
echo

if [ ! -d backend/.venv ]; then python3 -m venv backend/.venv; fi
# shellcheck disable=SC1091
. backend/.venv/bin/activate
pip install --quiet -r backend/requirements.txt

python3 scripts/verify_api_reports.py
