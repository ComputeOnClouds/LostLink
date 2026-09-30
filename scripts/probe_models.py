#!/usr/bin/env python3
"""Probe both Bedrock models live: Titan text embedding + Claude vision (via inference
profile). Reports which work right now so we know if the Anthropic gate has cleared."""
import base64
import json
import os
import boto3
from botocore.exceptions import ClientError

REGION = os.environ.get("BEDROCK_REGION", os.environ.get("AWS_REGION", "ap-southeast-2"))
TITAN = "amazon.titan-embed-text-v2:0"
CLAUDE = "au.anthropic.claude-haiku-4-5-20251001-v1:0"
brt = boto3.client("bedrock-runtime", region_name=REGION)

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)

print(f"Region: {REGION}\n")

print("1. Titan text embedding:")
try:
    r = brt.invoke_model(modelId=TITAN, body=json.dumps({"inputText": "black leather wallet"}))
    v = json.loads(r["body"].read())["embedding"]
    print(f"   OK  dim={len(v)}")
except ClientError as e:
    print(f"   FAIL {e.response['Error']['Code']}: {e.response['Error']['Message'][:110]}")

print("2. Claude vision (photo -> description):")
try:
    body = {
        "anthropic_version": "bedrock-2023-05-31", "max_tokens": 60,
        "messages": [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png",
             "data": base64.b64encode(PNG).decode()}},
            {"type": "text", "text": "Describe this image in one short phrase."}]}],
    }
    r = brt.invoke_model(modelId=CLAUDE, body=json.dumps(body))
    out = json.loads(r["body"].read())
    txt = "".join(b.get("text", "") for b in out.get("content", []))
    print(f"   OK  -> {txt[:70]!r}")
except ClientError as e:
    print(f"   FAIL {e.response['Error']['Code']}: {e.response['Error']['Message'][:150]}")
