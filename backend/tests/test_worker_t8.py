"""Task 8 unit tests: worker orchestration + BruteForceRetriever with fakes.

Exercises the full handle() flow with in-memory fakes (no AWS): enrichment (description
+ embedding caching), cross-org retrieval, scoring via the real BlendedScorer +
DefaultProfileSelector, match persistence above threshold, and orientation
(query=lost, candidate=found) regardless of which side triggered the job.
"""

import os

from pipeline.models import Item, ItemType, VectorMap, OrgScope
from pipeline.impl.retriever import BruteForceRetriever
from pipeline.impl.scorer import BlendedScorer
from pipeline.impl.profile import DefaultProfileSelector
from pipeline.worker import MatchWorker


class FakeRepo:
    def __init__(self):
        self.items = {}
        self.saved_matches = []

    def get(self, item_id):
        return self.items[item_id]

    def save(self, item):
        self.items[item.item_id] = item

    def list_candidates(self, query_item, org_scope):
        opposing = query_item.item_type.opposing
        return [
            i for i in self.items.values()
            if i.item_type is opposing and i.item_id != query_item.item_id
        ]

    def save_match(self, match):
        self.saved_matches.append(match)


class FakeDescriptionSource:
    def describe(self, item):
        return item.description or "generated description"


class FakeEmbedder:
    """Deterministic 3-d embedding keyed by a canned map, for predictable cosine."""
    def __init__(self, vectors):
        self._vectors = vectors

    def embed(self, item):
        return VectorMap(text=self._vectors.get(item.item_id, [1.0, 0.0, 0.0]))


class RecordingNotifier:
    def __init__(self):
        self.calls = []

    def notify(self, owner_id, match):
        self.calls.append((owner_id, match))


def _make_worker(repo, vectors, notifier=None):
    return MatchWorker(
        repository=repo,
        description_source=FakeDescriptionSource(),
        embedder=FakeEmbedder(vectors),
        retriever=BruteForceRetriever(repo),
        profile_selector=DefaultProfileSelector(),
        scorer=BlendedScorer(),
        notifier=notifier or RecordingNotifier(),
    )


def _lost(**kw):
    d = dict(item_id="lost-1", item_type=ItemType.LOST, organisation_id="individual",
             owner_id="user-1", description="black wallet", location_zone="z1",
             event_time="2026-09-29T10:00:00+00:00")
    d.update(kw)
    return Item(**d)


def _found(**kw):
    d = dict(item_id="found-1", item_type=ItemType.FOUND, organisation_id="org-nus",
             owner_id="staff-1", description="dark wallet", location_zone="z1",
             event_time="2026-09-29T12:00:00+00:00", status="available")
    d.update(kw)
    return Item(**d)


def test_retriever_delegates_and_excludes_self():
    repo = FakeRepo()
    repo.save(_lost())
    repo.save(_found())
    r = BruteForceRetriever(repo)
    cands = r.retrieve(repo.get("lost-1"), OrgScope(all_authorised=True))
    ids = {c.item_id for c in cands}
    assert ids == {"found-1"}  # opposing type only, excludes the query itself


def test_worker_enriches_and_persists_match_above_threshold(monkeypatch):
    # Identical vectors -> cosine 1.0 -> text term 1.0; same zone -> spatial 1.0;
    # 2h apart -> temporal ~0.98. Weighted score well above default 0.7 threshold.
    monkeypatch.setenv("MATCH_THRESHOLD", "0.7")
    repo = FakeRepo()
    lost = _lost(vectors=VectorMap())  # empty -> worker must embed
    found = _found(vectors=VectorMap(text=[1.0, 0.0, 0.0]))
    repo.save(lost)
    repo.save(found)
    notifier = RecordingNotifier()
    worker = _make_worker(repo, {"lost-1": [1.0, 0.0, 0.0]}, notifier)

    worker.handle({"itemId": "lost-1", "type": "lost"})

    # embedding cached on the lost item
    assert repo.get("lost-1").vectors.has_text()
    # one match persisted, oriented lost->found
    assert len(repo.saved_matches) == 1
    m = repo.saved_matches[0]
    assert m.query_item_id == "lost-1" and m.candidate_item_id == "found-1"
    assert m.organisation_id == "org-nus"
    assert m.score >= 0.7
    # owner notified
    assert notifier.calls and notifier.calls[0][0] == "user-1"


def test_worker_orients_when_found_item_triggers(monkeypatch):
    monkeypatch.setenv("MATCH_THRESHOLD", "0.7")
    repo = FakeRepo()
    repo.save(_lost(vectors=VectorMap(text=[1.0, 0.0, 0.0])))
    repo.save(_found(vectors=VectorMap()))  # found triggers, needs embedding
    worker = _make_worker(repo, {"found-1": [1.0, 0.0, 0.0]})

    worker.handle({"itemId": "found-1", "type": "found"})

    assert len(repo.saved_matches) == 1
    m = repo.saved_matches[0]
    # oriented: query is always the lost report
    assert m.query_item_id == "lost-1" and m.candidate_item_id == "found-1"


def test_worker_no_match_below_threshold(monkeypatch):
    monkeypatch.setenv("MATCH_THRESHOLD", "0.95")
    repo = FakeRepo()
    repo.save(_lost(vectors=VectorMap(text=[1.0, 0.0, 0.0]), location_zone="z1"))
    # orthogonal vector -> cosine 0 -> text term 0.5 after remap; different zone -> 0.1
    repo.save(_found(vectors=VectorMap(text=[0.0, 1.0, 0.0]), location_zone="z9",
                     event_time="2026-01-01T00:00:00+00:00"))
    worker = _make_worker(repo, {})
    worker.handle({"itemId": "lost-1", "type": "lost"})
    assert repo.saved_matches == []


def test_worker_skips_withdrawn(monkeypatch):
    repo = FakeRepo()
    repo.save(_lost(status="withdrawn", vectors=VectorMap(text=[1.0, 0.0, 0.0])))
    repo.save(_found(vectors=VectorMap(text=[1.0, 0.0, 0.0])))
    worker = _make_worker(repo, {})
    worker.handle({"itemId": "lost-1", "type": "lost"})
    assert repo.saved_matches == []


# ---- report status lifecycle (pending_match -> matched / no_match) -----------------

from pipeline.models import STATUS_MATCHED, STATUS_NO_MATCH, STATUS_PENDING_MATCH  # noqa: E402


def test_report_status_becomes_matched(monkeypatch):
    monkeypatch.setenv("MATCH_THRESHOLD", "0.7")
    repo = FakeRepo()
    repo.save(_lost(status=STATUS_PENDING_MATCH, vectors=VectorMap(text=[1.0, 0.0, 0.0])))
    repo.save(_found(vectors=VectorMap(text=[1.0, 0.0, 0.0])))
    worker = _make_worker(repo, {})
    worker.handle({"itemId": "lost-1", "type": "lost"})
    assert repo.get("lost-1").status == STATUS_MATCHED


def test_report_status_becomes_no_match(monkeypatch):
    monkeypatch.setenv("MATCH_THRESHOLD", "0.95")
    repo = FakeRepo()
    repo.save(_lost(status=STATUS_PENDING_MATCH, vectors=VectorMap(text=[1.0, 0.0, 0.0]),
                    location_zone="z1"))
    # orthogonal vector + different zone + far time -> below 0.95
    repo.save(_found(vectors=VectorMap(text=[0.0, 1.0, 0.0]), location_zone="z9",
                     event_time="2026-01-01T00:00:00+00:00"))
    worker = _make_worker(repo, {})
    worker.handle({"itemId": "lost-1", "type": "lost"})
    assert repo.get("lost-1").status == STATUS_NO_MATCH


def test_found_trigger_flips_affected_lost_report_to_matched(monkeypatch):
    monkeypatch.setenv("MATCH_THRESHOLD", "0.7")
    repo = FakeRepo()
    repo.save(_lost(status=STATUS_PENDING_MATCH, vectors=VectorMap(text=[1.0, 0.0, 0.0])))
    repo.save(_found(vectors=VectorMap(text=[1.0, 0.0, 0.0])))
    worker = _make_worker(repo, {})
    # a FOUND item triggers the job; the matching lost report should flip to matched
    worker.handle({"itemId": "found-1", "type": "found"})
    assert repo.get("lost-1").status == STATUS_MATCHED
    # the found item keeps its own status (not matched/no_match)
    assert repo.get("found-1").status == "available"


def test_deleted_item_job_is_skipped_gracefully():
    repo = FakeRepo()  # empty — item was purged
    worker = _make_worker(repo, {})
    worker.handle({"itemId": "lost-gone", "type": "lost"})  # must not raise
    assert repo.saved_matches == []
