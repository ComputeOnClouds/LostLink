"""Embedder + DescriptionSource over an OpenAI-compatible API (e.g. NUS SoClaaS, Ollama).

Used by the local Docker stack in place of Bedrock (docs/LOCAL.md); selected with
EMBEDDER=openai / DESCRIPTION_SOURCE=openai. Env: LLM_BASE_URL, LLM_API_KEY,
LLM_EMBED_MODEL, LLM_VISION_MODEL.
"""

from __future__ import annotations

import base64
import json
import os
import re
from urllib.request import Request, urlopen

from ..interfaces import Embedder
from ..models import Item, VectorMap
from .description import _PROMPT, ClaudeDescriptionSource, _clean_description


def _post(path: str, payload: dict) -> dict:
    request = Request(
        os.environ["LLM_BASE_URL"].rstrip("/") + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {os.environ.get('LLM_API_KEY', '')}"},
    )
    with urlopen(request, timeout=60) as response:
        return json.load(response)


class OpenAICompatEmbedder(Embedder):
    def embed(self, item: Item) -> VectorMap:
        text = (item.description or "").strip()
        if not text:
            return VectorMap()
        data = _post("/embeddings", {"model": os.environ["LLM_EMBED_MODEL"], "input": text})
        return VectorMap(text=data["data"][0]["embedding"])


class OpenAICompatDescriptionSource(ClaudeDescriptionSource):
    """Same photo fetch and typed-text fallback as the Claude source; only the model call differs."""

    def _invoke_claude(self, image_bytes: bytes, media_type: str) -> str:
        image = f"data:{media_type};base64,{base64.b64encode(image_bytes).decode()}"
        data = _post("/chat/completions", {
            "model": os.environ["LLM_VISION_MODEL"],
            "max_tokens": 300,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": image}},
                {"type": "text", "text": _PROMPT},
            ]}],
        })
        text = data["choices"][0]["message"].get("content") or ""
        # Reasoning models may inline their thinking before the answer.
        return _clean_description(re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL))
