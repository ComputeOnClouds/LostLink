#!/usr/bin/env python3
"""Probe live Bedrock access: a Titan text embedding and a Claude text/vision call.

Tries a few model-id / inference-profile variants and reports which work, so Task 7 can
pin the right ids. Newer Anthropic models in non-US regions often require a regional
inference-profile id (e.g. "apac.anthropic.<model>").
"""
import base64
import json
import os
import sys

import boto3
from botocore.exceptions import ClientError

REGION = os.environ.get("AWS_REGION", "ap-southeast-2")
brt = boto3.client("bedrock-runtime", region_name=REGION)

# 1x1 png
PNG_1x1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def try_titan(model_id):
    try:
        resp = brt.invoke_model(
            modelId=model_id,
            body=json.dumps({"inputText": "black leather wallet"}),
        )
        vec = json.loads(resp["body"].read())["embedding"]
        print(f"  [OK  ] titan {model_id}: dim={len(vec)}")
        return len(vec)
    except ClientError as e:
        print(f"  [FAIL] titan {model_id}: {e.response['Error']['Code']}: {e.response['Error']['Message'][:90]}")
        return None


def try_claude_text(model_id):
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 50,
        "messages": [{"role": "user", "content": [{"type": "text", "text": "Say OK."}]}],
    }
    try:
        resp = brt.invoke_model(modelId=model_id, body=json.dumps(body))
        out = json.loads(resp["body"].read())
        txt = out["content"][0]["text"]
        print(f"  [OK  ] claude-text {model_id}: {txt[:40]!r}")
        return True
    except ClientError as e:
        print(f"  [FAIL] claude-text {model_id}: {e.response['Error']['Code']}: {e.response['Error']['Message'][:90]}")
        return False


def try_claude_vision(model_id):
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 60,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                 "data": base64.b64encode(PNG_1x1).decode()}},
                {"type": "text", "text": "Describe this image in one short phrase."},
            ],
        }],
    }
    try:
        resp = brt.invoke_model(modelId=model_id, body=json.dumps(body))
        out = json.loads(resp["body"].read())
        txt = out["content"][0]["text"]
        print(f"  [OK  ] claude-vision {model_id}: {txt[:50]!r}")
        return True
    except ClientError as e:
        print(f"  [FAIL] claude-vision {model_id}: {e.response['Error']['Code']}: {e.response['Error']['Message'][:90]}")
        return False


print(f"Region: {REGION}")
print("Titan text embeddings:")
for m in ["amazon.titan-embed-text-v2:0", "amazon.titan-embed-text-v1"]:
    try_titan(m)

print("Claude (text then vision), trying on-demand id and apac inference profile:")
for m in [
    "anthropic.claude-haiku-4-5-20251001-v1:0",
    "apac.anthropic.claude-haiku-4-5-20251001-v1:0",
    "anthropic.claude-sonnet-4-5-20250929-v1:0",
    "apac.anthropic.claude-sonnet-4-5-20250929-v1:0",
]:
    ok = try_claude_text(m)
    if ok:
        try_claude_vision(m)
