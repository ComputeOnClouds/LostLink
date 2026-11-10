"""OpenAI-compatible pipeline stages (the local stack's Bedrock replacement)."""

import io

from pipeline import factory
from pipeline.impl import openai_compat
from pipeline.models import Item, ItemType


def _item(**kw):
    return Item(item_id="i1", item_type=ItemType.LOST, organisation_id="o", owner_id="u", **kw)


class FakeS3:
    def get_object(self, Bucket=None, Key=None):
        return {"Body": io.BytesIO(b"img")}


def test_embedder_returns_text_vector(monkeypatch):
    calls = []
    monkeypatch.setenv("LLM_EMBED_MODEL", "bge-m3")
    monkeypatch.setattr(openai_compat, "_post", lambda path, body: calls.append((path, body)) or {"data": [{"embedding": [0.1, 0.2]}]})
    assert openai_compat.OpenAICompatEmbedder().embed(_item(description=" wallet ")).text == [0.1, 0.2]
    assert calls == [("/embeddings", {"model": "bge-m3", "input": "wallet"})]


def test_description_from_photo_is_cleaned(monkeypatch):
    calls = []
    monkeypatch.setenv("LLM_VISION_MODEL", "qwen3-vl:32b")
    reply = {"choices": [{"message": {"content": "<think>hmm</think>\nDescription: black wallet"}}]}
    monkeypatch.setattr(openai_compat, "_post", lambda path, body: calls.append(body) or reply)
    source = openai_compat.OpenAICompatDescriptionSource(s3_client=FakeS3())
    assert source.describe(_item(photo_key="o/i1/p.png")) == "black wallet"
    assert calls[0]["messages"][0]["content"][0]["image_url"]["url"] == "data:image/png;base64,aW1n"


def test_factory_selects_openai_stages(monkeypatch):
    monkeypatch.setenv("EMBEDDER", "openai")
    monkeypatch.setenv("DESCRIPTION_SOURCE", "openai")
    assert isinstance(factory.make_embedder(), openai_compat.OpenAICompatEmbedder)
    assert isinstance(factory.make_description_source(), openai_compat.OpenAICompatDescriptionSource)
