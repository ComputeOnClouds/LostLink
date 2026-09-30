"""DescriptionSource implementation — Amazon Bedrock Claude (Task 7).

Option 1 (RATIONALE ADR-003): if the item has a photo, generate a structured text
description from it via Claude (vision); otherwise use the typed description. The photo
is used only to produce text — no image embedding contributes to matching.

Config-driven so the model / region can change without code:
    DESCRIBE_MODEL_ID  default anthropic.claude-haiku-4-5-20251001-v1:0
    BEDROCK_REGION     default AWS_REGION (falls back to ap-southeast-2)
    PHOTOS_BUCKET      S3 bucket holding item photos
"""

from __future__ import annotations

import base64
import json
import os

from ..interfaces import DescriptionSource
from ..models import Item

# Claude 4.5 Haiku requires an inference-profile id (on-demand invoke is unsupported).
# In ap-southeast-2 the regional profile is prefixed "au.". Override via DESCRIBE_MODEL_ID.
_DEFAULT_MODEL = "au.anthropic.claude-haiku-4-5-20251001-v1:0"

# A tight prompt: produce a compact, matchable description, no chit-chat. Consistent
# phrasing across items improves text-similarity matching (RATIONALE ADR-003).
_PROMPT = (
    "You are cataloguing a lost-and-found item from its photo. In 1-2 sentences, "
    "describe only the item: its type/category, main colours, brand or visible text, "
    "material, and any distinctive marks. Do not describe the background or guess "
    "personal details. Output the description only."
)

_MEDIA_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}


class ClaudeDescriptionSource(DescriptionSource):
    def __init__(self, bedrock_client=None, s3_client=None) -> None:
        self._model_id = os.environ.get("DESCRIBE_MODEL_ID", _DEFAULT_MODEL)
        self._region = os.environ.get("BEDROCK_REGION") or os.environ.get(
            "AWS_REGION", "ap-southeast-2"
        )
        self._bucket = os.environ.get("PHOTOS_BUCKET")
        self._bedrock = bedrock_client  # injectable for tests
        self._s3 = s3_client

    @property
    def bedrock(self):
        if self._bedrock is None:
            import boto3

            self._bedrock = boto3.client("bedrock-runtime", region_name=self._region)
        return self._bedrock

    @property
    def s3(self):
        if self._s3 is None:
            import boto3

            self._s3 = boto3.client("s3", region_name=self._region)
        return self._s3

    def describe(self, item: Item) -> str:
        # No photo: use whatever text the user/staff typed (may be empty).
        if not item.photo_key:
            return (item.description or "").strip()

        image_bytes = self._fetch_photo(item.photo_key)
        media_type = self._media_type(item.photo_key)
        generated = self._invoke_claude(image_bytes, media_type)

        # Prefer the generated description; if generation returns nothing, fall back to
        # any typed text so we never end up with an empty description when a photo exists.
        return generated.strip() or (item.description or "").strip()

    # ---- internals -----------------------------------------------------------------

    def _fetch_photo(self, key: str) -> bytes:
        obj = self.s3.get_object(Bucket=self._bucket, Key=key)
        return obj["Body"].read()

    @staticmethod
    def _media_type(key: str) -> str:
        ext = key.rsplit(".", 1)[-1].lower() if "." in key else ""
        return _MEDIA_TYPES.get(ext, "image/jpeg")

    def _invoke_claude(self, image_bytes: bytes, media_type: str) -> str:
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 200,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": base64.b64encode(image_bytes).decode(),
                            },
                        },
                        {"type": "text", "text": _PROMPT},
                    ],
                }
            ],
        }
        resp = self.bedrock.invoke_model(modelId=self._model_id, body=json.dumps(body))
        payload = json.loads(resp["body"].read())
        # Claude messages API returns content blocks; concatenate any text blocks.
        parts = [b.get("text", "") for b in payload.get("content", []) if b.get("type") == "text"]
        return " ".join(p for p in parts if p).strip()
