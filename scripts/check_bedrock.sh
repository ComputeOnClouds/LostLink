#!/usr/bin/env bash
# Probe Bedrock model availability in the target region.
set -euo pipefail
REGION="${AWS_REGION:-ap-southeast-2}"
echo "Region: $REGION"
echo "--- Titan embed / Claude models listed as available (may still need access grant):"
aws bedrock list-foundation-models --region "$REGION" \
  --query "modelSummaries[?contains(modelId,'titan-embed') || contains(modelId,'claude')].[modelId,inputModalities]" \
  --output text 2>&1 | sort || echo "list-foundation-models failed"
