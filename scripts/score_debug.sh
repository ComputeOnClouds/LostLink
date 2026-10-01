#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
cd "$(dirname "$0")/.."
REGION="${AWS_REGION:-ap-southeast-2}"
cfn_out() {
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$1" \
    --query "Stacks[0].Outputs[?ExportName=='$2'].OutputValue" --output text
}
export AWS_REGION="$REGION"
export ITEMS_TABLE="$(cfn_out LostLink-Data LostLink-ItemsTableName)"
# Scorer weights + threshold (defaults match the deployed matching stack).
export WEIGHT_TEXT="${WEIGHT_TEXT:-0.6}"
export WEIGHT_IMAGE="${WEIGHT_IMAGE:-0.0}"
export WEIGHT_LOCATION="${WEIGHT_LOCATION:-0.25}"
export WEIGHT_TIME="${WEIGHT_TIME:-0.15}"
export MATCH_THRESHOLD="${MATCH_THRESHOLD:-0.7}"
. backend/.venv/bin/activate
python3 scripts/score_debug.py
