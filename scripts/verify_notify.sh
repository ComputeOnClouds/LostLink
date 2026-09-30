#!/usr/bin/env bash
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
export MATCHES_TABLE="$(cfn_out LostLink-Data LostLink-MatchesTableName)"
export MATCH_QUEUE_URL="$(cfn_out LostLink-Data LostLink-MatchQueueUrl)"

. backend/.venv/bin/activate
pip install --quiet -r backend/requirements.txt
python3 scripts/verify_notify.py
