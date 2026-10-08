"""Embedder implementation — Amazon Titan Text Embeddings (Task 7).

Produces a text embedding for an item's description and returns it in a VectorMap with
the ``image`` slot left empty (reserved for Option 2; see RATIONALE ADR-003). No image
embedding contributes to matching today.

Model + region are config-driven so the stage can point at a different model or a
cross-region Bedrock endpoint without code changes:
    EMBED_MODEL_ID   default amazon.titan-embed-text-v2:0  (1024-dim)
    EMBED_BEDROCK_REGION optional embedding endpoint override
    BEDROCK_REGION   default AWS_REGION (falls back to ap-southeast-2)
"""

from __future__ import annotations

import json
import os

from ..interfaces import Embedder
from ..models import Item, VectorMap

_DEFAULT_MODEL = "amazon.titan-embed-text-v2:0"


class TitanEmbedder(Embedder):
    def __init__(self, client=None) -> None:
        self._model_id = os.environ.get("EMBED_MODEL_ID", _DEFAULT_MODEL)
        self._region = (
            os.environ.get("EMBED_BEDROCK_REGION")
            or os.environ.get("BEDROCK_REGION")
            or os.environ.get("AWS_REGION", "ap-southeast-2")
        )
        self._client = client  # injectable for tests

    @property
    def client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client("bedrock-runtime", region_name=self._region)
        return self._client

    def embed(self, item: Item) -> VectorMap:
        text = (item.description or "").strip()
        if not text:
            # Nothing to embed (e.g. a report awaiting photo->description). Return an
            # empty VectorMap; the worker will have run DescriptionSource first, so this
            # is a defensive guard rather than the normal path.
            return VectorMap()

        resp = self.client.invoke_model(
            modelId=self._model_id,
            body=json.dumps({"inputText": text}),
        )
        payload = json.loads(resp["body"].read())
        return VectorMap(text=payload["embedding"], image=None)
