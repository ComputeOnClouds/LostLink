#!/usr/bin/env bash
# Read-only: show current row counts in each table + the Cognito users, so we know
# exactly what "dummy data" exists before deciding what to clear.
set -euo pipefail
REGION="${AWS_REGION:-ap-southeast-2}"
cfn_out() {
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$1" \
    --query "Stacks[0].Outputs[?ExportName=='$2'].OutputValue" --output text
}
ITEMS=$(cfn_out LostLink-Data LostLink-ItemsTableName)
CLAIMS=$(cfn_out LostLink-Data LostLink-ClaimsTableName)
MATCHES=$(cfn_out LostLink-Data LostLink-MatchesTableName)
ORGS=$(cfn_out LostLink-Data LostLink-OrganisationsTableName)
POOL=$(cfn_out LostLink-Auth LostLink-UserPoolId)

for t in "$ITEMS" "$CLAIMS" "$MATCHES" "$ORGS"; do
  n=$(aws dynamodb scan --region "$REGION" --table-name "$t" --select COUNT --query Count --output text)
  echo "table $t: $n items"
done
echo "--- Cognito users:"
aws cognito-idp list-users --region "$REGION" --user-pool-id "$POOL" \
  --query 'Users[].Username' --output text | tr '\t' '\n'
