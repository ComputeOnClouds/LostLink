#!/usr/bin/env bash
# Clear all runtime/demo data from the deployed app: every row in the Items, Matches,
# Claims and Organisations tables, plus all Cognito demo users. Does NOT touch infra or
# the committed eval sample dataset. Re-seed users afterwards with seed_demo.sh.
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

# ---- clear a single-PK table -------------------------------------------------------
clear_pk() {
  local table="$1" pk="$2"
  echo "Clearing $table (pk=$pk)..."
  local keys
  keys=$(aws dynamodb scan --region "$REGION" --table-name "$table" \
    --projection-expression "#k" --expression-attribute-names "{\"#k\":\"$pk\"}" \
    --query "Items[].$pk.S" --output text)
  local n=0
  for id in $keys; do
    aws dynamodb delete-item --region "$REGION" --table-name "$table" \
      --key "{\"$pk\":{\"S\":\"$id\"}}" >/dev/null
    n=$((n+1))
  done
  echo "  deleted $n"
}

# ---- clear the Matches table (composite key queryItemId + candidateItemId) ----------
clear_matches() {
  echo "Clearing $MATCHES (pk=queryItemId, sk=candidateItemId)..."
  local rows
  rows=$(aws dynamodb scan --region "$REGION" --table-name "$MATCHES" \
    --projection-expression "queryItemId,candidateItemId" \
    --query "Items[].[queryItemId.S,candidateItemId.S]" --output text)
  local n=0
  # rows is tab/newline separated pairs
  while read -r q c; do
    [ -z "${q:-}" ] && continue
    aws dynamodb delete-item --region "$REGION" --table-name "$MATCHES" \
      --key "{\"queryItemId\":{\"S\":\"$q\"},\"candidateItemId\":{\"S\":\"$c\"}}" >/dev/null
    n=$((n+1))
  done <<< "$rows"
  echo "  deleted $n"
}

clear_pk "$ITEMS" itemId
clear_pk "$CLAIMS" claimId
clear_pk "$ORGS" organisationId
clear_matches

echo "Deleting Cognito users..."
users=$(aws cognito-idp list-users --region "$REGION" --user-pool-id "$POOL" \
  --query 'Users[].Username' --output text)
for u in $users; do
  aws cognito-idp admin-delete-user --region "$REGION" --user-pool-id "$POOL" --username "$u" >/dev/null
  echo "  deleted user $u"
done

echo "Done. Re-seed demo users with: bash scripts/seed_demo.sh"
