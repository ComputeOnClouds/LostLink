#!/usr/bin/env bash
set -euo pipefail
REGION="${AWS_REGION:-ap-southeast-2}"
aws lambda list-functions --region "$REGION" \
  --query "Functions[?starts_with(FunctionName, 'LostLink')].FunctionName" \
  --output text | tr '\t' '\n'
