"""Item categories: classification requests and the worker's category filter."""

import io
import json

from pipeline import category
from pipeline.impl.description import ClaudeDescriptionSource
from pipeline.models import VectorMap
from test_worker_t8 import FakeRepo, RecordingNotifier, _found, _lost, _make_worker


def test_parse_and_compatible():
    assert category.parse("Category: Wallet.") == "wallet"
    assert category.parse("headphones") == "other"  # not a category name ("phone" inside a word)
    assert category.compatible("wallet", "wallet") and category.compatible("wallet", "other")
    assert category.compatible(None, "bag") and not category.compatible("wallet", "bottle")


class FakeBedrock:
    def __init__(self, reply):
        self.reply, self.bodies = reply, []

    def invoke_model(self, modelId=None, body=None):
        self.bodies.append(json.loads(body))
        return {"body": io.BytesIO(json.dumps({"content": [{"type": "text", "text": self.reply}]}).encode())}


class FakeS3:
    def get_object(self, Bucket=None, Key=None):
        return {"Body": io.BytesIO(b"img")}


def test_classify_uses_photo_when_present_else_description():
    bedrock = FakeBedrock("bottle")
    src = ClaudeDescriptionSource(bedrock_client=bedrock, s3_client=FakeS3())
    assert src.classify(_found(photo_key="o/f/p.png")) == "bottle"
    assert [b["type"] for b in bedrock.bodies[0]["messages"][0]["content"]] == ["image", "text"]
    assert src.classify(_lost(description="blue flask")) == "bottle"
    text_only = bedrock.bodies[1]["messages"][0]["content"]
    assert len(text_only) == 1 and text_only[0]["text"].endswith("Item description: blue flask")


class FakeClassifier:
    def __init__(self, labels):
        self.labels = labels

    def describe(self, item):
        return item.description

    def classify(self, item):
        return self.labels[item.item_id]


def _run(lost_label, found_category):
    repo, notifier = FakeRepo(), RecordingNotifier()
    repo.save(_lost(vectors=VectorMap(text=[1.0, 0.0, 0.0])))
    # The found item was classified by its own job when it was registered.
    repo.save(_found(vectors=VectorMap(text=[1.0, 0.0, 0.0]), category=found_category, category_basis="dark wallet"))
    worker = _make_worker(repo, {}, notifier)
    worker.description_source = FakeClassifier({"lost-1": lost_label})
    worker.handle({"itemId": "lost-1", "type": "lost"})
    return repo


def test_worker_never_matches_different_categories():
    repo = _run("wallet", "bottle")
    assert repo.saved_matches == []  # identical text, same place and time, different kind of item
    assert repo.get("lost-1").category == "wallet"


def test_worker_matches_same_or_unknown_category():
    assert len(_run("wallet", "wallet").saved_matches) == 1
    assert len(_run("wallet", None).saved_matches) == 1  # items from before categories existed
