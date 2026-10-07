"""Task 7 unit tests for DescriptionSource and Embedder with mocked Bedrock/S3.

These assert the exact request payloads sent to Bedrock and correct parsing of
responses, so behaviour is pinned without a live AWS call. A separate live integration
check (scripts/verify_bedrock.py) exercises the real models once account verification
clears.
"""

import io
import json

from pipeline.models import Item, ItemType
from pipeline.impl.embedder import TitanEmbedder
from pipeline.impl.description import ClaudeDescriptionSource, _clean_description


def test_clean_description_strips_heading_label_quotes():
    # Markdown heading + body -> just the body line.
    assert _clean_description("# Lost-and-Found Item Description\nA blue leather wallet.") \
        == "A blue leather wallet."
    # Leading label removed.
    assert _clean_description("Description: red umbrella") == "red umbrella"
    # Surrounding quotes + whitespace collapsed.
    assert _clean_description('  "black   backpack"  ') == "black backpack"
    # Bullet marker removed.
    assert _clean_description("- teal water bottle") == "teal water bottle"
    # Plain text passes through.
    assert _clean_description("silver watch") == "silver watch"


class _Body:
    def __init__(self, data: dict):
        self._raw = json.dumps(data).encode()

    def read(self):
        return self._raw


class FakeBedrock:
    """Records the last invoke_model call and returns a canned response."""

    def __init__(self, response: dict):
        self._response = response
        self.last_model_id = None
        self.last_body = None

    def invoke_model(self, modelId=None, body=None):
        self.last_model_id = modelId
        self.last_body = json.loads(body)
        return {"body": _Body(self._response)}


class FakeS3:
    def __init__(self, data: bytes):
        self._data = data
        self.last_get = None

    def get_object(self, Bucket=None, Key=None):
        self.last_get = (Bucket, Key)
        return {"Body": io.BytesIO(self._data)}


# ---- Embedder -----------------------------------------------------------------------


def _lost(desc="black leather wallet", photo=None):
    return Item(
        item_id="lost-1",
        item_type=ItemType.LOST,
        organisation_id="individual",
        owner_id="u1",
        description=desc,
        photo_key=photo,
    )


def test_embedder_sends_inputtext_and_parses_vector():
    fake = FakeBedrock({"embedding": [0.1, 0.2, 0.3]})
    emb = TitanEmbedder(client=fake)
    vm = emb.embed(_lost("blue umbrella"))
    # request payload
    assert fake.last_body == {"inputText": "blue umbrella"}
    assert fake.last_model_id == "amazon.titan-embed-text-v2:0"
    # response parsing -> text slot populated, image slot reserved/empty
    assert vm.text == [0.1, 0.2, 0.3]
    assert vm.has_text()
    assert not vm.has_image()


def test_embedder_empty_description_returns_empty_vectormap():
    fake = FakeBedrock({"embedding": [0.1]})
    emb = TitanEmbedder(client=fake)
    vm = emb.embed(_lost(desc=""))
    assert not vm.has_text()
    assert fake.last_body is None  # no Bedrock call made


def test_embedding_endpoint_override_keeps_description_endpoint_in_deployment_region(monkeypatch):
    import boto3

    monkeypatch.setenv("BEDROCK_REGION", "ap-southeast-1")
    monkeypatch.setenv("EMBED_BEDROCK_REGION", "ap-southeast-2")
    calls = []
    monkeypatch.setattr(boto3, "client", lambda service, region_name: calls.append((service, region_name)))

    TitanEmbedder().client
    ClaudeDescriptionSource().bedrock

    assert calls == [
        ("bedrock-runtime", "ap-southeast-2"),
        ("bedrock-runtime", "ap-southeast-1"),
    ]


# ---- DescriptionSource --------------------------------------------------------------


def test_description_no_photo_uses_typed_text():
    bedrock = FakeBedrock({"content": [{"type": "text", "text": "SHOULD NOT BE USED"}]})
    src = ClaudeDescriptionSource(bedrock_client=bedrock, s3_client=FakeS3(b""))
    out = src.describe(_lost(desc="  red backpack  ", photo=None))
    assert out == "red backpack"
    assert bedrock.last_body is None  # no vision call without a photo


def test_description_with_photo_calls_claude_vision_and_parses():
    bedrock = FakeBedrock({"content": [{"type": "text", "text": "A black leather wallet."}]})
    s3 = FakeS3(b"\x89PNGfakebytes")
    src = ClaudeDescriptionSource(bedrock_client=bedrock, s3_client=s3)
    # ensure the bucket is read from env-independent injection
    src._bucket = "photos-bucket"
    item = _lost(desc="", photo="org-nus/found-1/abc.png")
    out = src.describe(item)

    # fetched the right object
    assert s3.last_get == ("photos-bucket", "org-nus/found-1/abc.png")
    # request shape: image block (base64 png) + text prompt
    msg = bedrock.last_body["messages"][0]["content"]
    assert msg[0]["type"] == "image"
    assert msg[0]["source"]["media_type"] == "image/png"
    assert msg[0]["source"]["type"] == "base64"
    assert msg[1]["type"] == "text"
    assert bedrock.last_body["anthropic_version"] == "bedrock-2023-05-31"
    # response parsing
    assert out == "A black leather wallet."


def test_description_with_photo_falls_back_to_typed_when_generation_empty():
    bedrock = FakeBedrock({"content": [{"type": "text", "text": "   "}]})
    src = ClaudeDescriptionSource(bedrock_client=bedrock, s3_client=FakeS3(b"x"))
    src._bucket = "b"
    out = src.describe(_lost(desc="fallback text", photo="a/b/c.jpg"))
    assert out == "fallback text"


def test_description_media_type_by_extension():
    src = ClaudeDescriptionSource(bedrock_client=FakeBedrock({"content": []}), s3_client=FakeS3(b"x"))
    assert src._media_type("a/b.jpg") == "image/jpeg"
    assert src._media_type("a/b.jpeg") == "image/jpeg"
    assert src._media_type("a/b.png") == "image/png"
    assert src._media_type("a/b.webp") == "image/webp"
    assert src._media_type("a/b.unknown") == "image/jpeg"  # safe default
