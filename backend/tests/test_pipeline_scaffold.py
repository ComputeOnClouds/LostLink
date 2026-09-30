"""Scaffold smoke tests (Task 1).

Confirms the pipeline package imports cleanly, the interfaces are abstract, the factory
wires implementations by env var, and unimplemented stubs raise NotImplementedError
rather than silently doing the wrong thing.
"""

import pytest

import pipeline
from pipeline import factory
from pipeline.models import Item, ItemType, VectorMap, OrgScope
from pipeline.worker import MatchWorker


def test_package_imports():
    assert pipeline.Item is Item
    assert pipeline.ItemType is ItemType


def test_itemtype_opposing():
    assert ItemType.LOST.opposing is ItemType.FOUND
    assert ItemType.FOUND.opposing is ItemType.LOST


def test_vectormap_slots():
    vm = VectorMap(text=[0.1, 0.2])
    assert vm.has_text()
    assert not vm.has_image()  # image slot reserved for the future


def test_factory_defaults_wire_up():
    # Default implementations should instantiate without error.
    repo = factory.make_repository()
    assert factory.make_description_source() is not None
    assert factory.make_embedder() is not None
    assert factory.make_retriever(repo) is not None
    assert factory.make_scorer() is not None
    assert factory.make_profile_selector() is not None
    assert factory.make_notifier() is not None


def test_factory_rejects_unknown(monkeypatch):
    monkeypatch.setenv("RETRIEVER", "nope")
    with pytest.raises(ValueError):
        factory.make_retriever(factory.make_repository())


def test_worker_builds_from_env():
    worker = MatchWorker.from_env()
    assert isinstance(worker, MatchWorker)


def test_worker_handle_is_implemented():
    # handle() is implemented (Task 8); a job with no itemId is handled gracefully
    # (logs + returns) rather than raising.
    worker = MatchWorker.from_env()
    worker.handle({})  # no itemId -> no-op, must not raise


def test_ann_retriever_is_stub_only():
    # The scaling retriever remains a documented stub (RATIONALE ADR-006).
    from pipeline.impl.retriever import AnnRetriever
    from pipeline.models import Item, ItemType, OrgScope

    with pytest.raises(NotImplementedError):
        AnnRetriever().retrieve(
            Item(item_id="x", item_type=ItemType.LOST, organisation_id="o", owner_id="u"),
            OrgScope(),
        )
