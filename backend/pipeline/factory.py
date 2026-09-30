"""Wires concrete pipeline implementations from environment variables.

The MatchWorker never imports concrete classes directly; it asks the factory. This is
the single place where a stage implementation is chosen, so swapping an implementation
(e.g. RETRIEVER=ann once an AnnRetriever exists) is a config change, not a code change.

Environment variables (all optional; defaults chosen for the prototype):
    DESCRIPTION_SOURCE = claude      (default)
    EMBEDDER           = titan       (default)
    RETRIEVER          = bruteforce  (default) | ann
    SCORER             = blended     (default)
    PROFILE_SELECTOR   = default     (default)
    NOTIFIER           = ses         (default)
    REPOSITORY         = dynamo      (default)
"""

from __future__ import annotations

import os

from .interfaces import (
    DescriptionSource,
    Embedder,
    CandidateRetriever,
    Scorer,
    ProfileSelector,
    Notifier,
    ItemRepository,
)
from .impl import (
    ClaudeDescriptionSource,
    TitanEmbedder,
    BruteForceRetriever,
    AnnRetriever,
    BlendedScorer,
    DefaultProfileSelector,
    SesNotifier,
    DynamoItemRepository,
)


def make_repository() -> ItemRepository:
    choice = os.environ.get("REPOSITORY", "dynamo").lower()
    if choice == "dynamo":
        return DynamoItemRepository()
    raise ValueError(f"Unknown REPOSITORY implementation: {choice!r}")


def make_description_source() -> DescriptionSource:
    choice = os.environ.get("DESCRIPTION_SOURCE", "claude").lower()
    if choice == "claude":
        return ClaudeDescriptionSource()
    raise ValueError(f"Unknown DESCRIPTION_SOURCE implementation: {choice!r}")


def make_embedder() -> Embedder:
    choice = os.environ.get("EMBEDDER", "titan").lower()
    if choice == "titan":
        return TitanEmbedder()
    raise ValueError(f"Unknown EMBEDDER implementation: {choice!r}")


def make_retriever(repository: ItemRepository) -> CandidateRetriever:
    choice = os.environ.get("RETRIEVER", "bruteforce").lower()
    if choice == "bruteforce":
        return BruteForceRetriever(repository)
    if choice == "ann":
        return AnnRetriever()
    raise ValueError(f"Unknown RETRIEVER implementation: {choice!r}")


def make_scorer() -> Scorer:
    choice = os.environ.get("SCORER", "blended").lower()
    if choice == "blended":
        return BlendedScorer()
    raise ValueError(f"Unknown SCORER implementation: {choice!r}")


def make_profile_selector() -> ProfileSelector:
    choice = os.environ.get("PROFILE_SELECTOR", "default").lower()
    if choice == "default":
        return DefaultProfileSelector()
    raise ValueError(f"Unknown PROFILE_SELECTOR implementation: {choice!r}")


def make_notifier() -> Notifier:
    choice = os.environ.get("NOTIFIER", "ses").lower()
    if choice == "ses":
        return SesNotifier()
    raise ValueError(f"Unknown NOTIFIER implementation: {choice!r}")
