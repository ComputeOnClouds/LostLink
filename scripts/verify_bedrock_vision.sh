#!/usr/bin/env bash
# Upload a small real photo to the photos bucket, then run the Claude vision probe.
set -euo pipefail
cd "$(dirname "$0")/.."

REGION="${AWS_REGION:-ap-southeast-2}"
PHOTOS_BUCKET="$(aws cloudformation describe-stacks --region "$REGION" --stack-name LostLink-Data \
  --query "Stacks[0].Outputs[?ExportName=='LostLink-PhotosBucketName'].OutputValue" --output text)"

. backend/.venv/bin/activate
pip install --quiet pillow >/dev/null 2>&1 || pip install --quiet pillow

KEY="probe/sample-$(date +%s).png"
python3 - "$KEY" "$PHOTOS_BUCKET" "$REGION" <<'PY'
import sys, boto3
from PIL import Image, ImageDraw
key, bucket, region = sys.argv[1], sys.argv[2], sys.argv[3]
# A simple, recognisable object: a red rectangle "wallet" on white.
img = Image.new("RGB", (200, 140), "white")
d = ImageDraw.Draw(img)
d.rectangle([30, 40, 170, 110], fill=(120, 30, 30), outline=(60, 15, 15), width=4)
d.line([30, 75, 170, 75], fill=(60, 15, 15), width=3)
img.save("/tmp/sample.png")
boto3.client("s3", region_name=region).upload_file("/tmp/sample.png", bucket, key)
print("uploaded", key)
PY

export AWS_REGION="$REGION" PHOTOS_BUCKET="$PHOTOS_BUCKET" SAMPLE_PHOTO_KEY="$KEY"
python3 scripts/verify_bedrock.py

# cleanup
aws s3 rm "s3://$PHOTOS_BUCKET/$KEY" --region "$REGION" >/dev/null
echo "cleaned up $KEY"
