#!/usr/bin/env bash
# Task 3 live verification runner: sets table/bucket env from CFN outputs, runs the
# repository + presigned-URL checks inside the backend venv.
set -euo pipefail
cd "$(dirname "$0")/.."

REGION="${AWS_REGION:-ap-southeast-2}"
STACK="LostLink-Data"

get_out() {
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?ExportName=='$1'].OutputValue" --output text
}

export AWS_REGION="$REGION"
export ITEMS_TABLE="$(get_out LostLink-ItemsTableName)"
export MATCHES_TABLE="$(get_out LostLink-MatchesTableName)"
export PHOTOS_BUCKET="$(get_out LostLink-PhotosBucketName)"

echo "ITEMS_TABLE=$ITEMS_TABLE"
echo "MATCHES_TABLE=$MATCHES_TABLE"
echo "PHOTOS_BUCKET=$PHOTOS_BUCKET"
echo

# Ensure venv + boto3 present.
if [ ! -d backend/.venv ]; then
  python3 -m venv backend/.venv
fi
# shellcheck disable=SC1091
. backend/.venv/bin/activate
pip install --quiet -r backend/requirements.txt

python3 scripts/verify_data.py
