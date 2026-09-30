#!/usr/bin/env bash
set -euo pipefail
REGION="${AWS_REGION:-ap-southeast-2}"
B=$(aws cloudformation describe-stacks --region "$REGION" --stack-name LostLink-Data \
  --query "Stacks[0].Outputs[?ExportName=='LostLink-PhotosBucketName'].OutputValue" --output text)
n=$(aws s3 ls "s3://$B" --recursive --region "$REGION" 2>/dev/null | wc -l)
echo "photos in $B: $n"
if [ "$n" -gt 0 ]; then
  aws s3 rm "s3://$B" --recursive --region "$REGION" >/dev/null
  echo "cleared $n objects"
fi
