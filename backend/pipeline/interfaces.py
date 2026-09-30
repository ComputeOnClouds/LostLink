"""Abstract stage interfaces for the matching pipeline.

The MatchWorker depends only on these ABCs. Concrete implementations live in
``pipeline.impl`` and are wired by ``pipeline.factory`` from environment variables.

These are intentionally defined before their first implementation (Task 1) so that the
contracts are fixed and alternatives can be swapped later without touching the worker.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .models import Item, VectorMap, MatchResult, Profile, OrgScope


class DescriptionSource(ABC):
    """Produces the text description used for matching.

    Contract: given an item, return the text to embed. Implementations may generate
    from a photo (Claude), fall back to typed text, or combine both.
    """

    @abstractmethod
    def describe(self, item: Item) -> str:
        ...


class Embedder(ABC):
    """Produces a VectorMap for an item.

    Contract: return a VectorMap. Today only the ``text`` slot is populated; the
    ``image`` slot is reserved for a future image-embedding implementation.
    """

    @abstractmethod
    def embed(self, item: Item) -> VectorMap:
        ...


class CandidateRetriever(ABC):
    """Fetches candidate items to compare against.

    Contract: return the opposing-type items within the authorised org scope. MUST NOT
    score. Swapping brute-force for an ANN/vector-DB implementation changes *which*
    candidates are returned, never *how* they are scored.
    """

    @abstractmethod
    def retrieve(self, query_item: Item, org_scope: OrgScope) -> list[Item]:
        ...


class Scorer(ABC):
    """Scores a pair of items given a weight map. Pure — no AWS, no retrieval.

    Contract: same inputs always produce the same output. The evaluation harness calls
    this exact class with in-memory weights to sweep variants.
    """

    @abstractmethod
    def score(self, a: Item, b: Item, weights: dict[str, float]) -> MatchResult:
        ...


class ProfileSelector(ABC):
    """Chooses the scoring profile (weight map + threshold) for a pair.

    Contract: return the Profile to apply. Today a single text+location+time profile;
    the image-present profile hook lives here for the future.
    """

    @abstractmethod
    def select(self, a: Item, b: Item) -> Profile:
        ...


class Notifier(ABC):
    """Notifies a report owner of a match. Hides the delivery channel (SES today)."""

    @abstractmethod
    def notify(self, owner_id: str, match: MatchResult) -> None:
        ...


class ItemRepository(ABC):
    """Persistence boundary. Hides DynamoDB from the pipeline."""

    @abstractmethod
    def get(self, item_id: str) -> Item:
        ...

    @abstractmethod
    def save(self, item: Item) -> None:
        ...

    @abstractmethod
    def list_candidates(self, query_item: Item, org_scope: OrgScope) -> list[Item]:
        ...

    @abstractmethod
    def save_match(self, match: MatchResult) -> None:
        ...
