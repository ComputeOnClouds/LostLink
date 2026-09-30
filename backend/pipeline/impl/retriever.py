"""CandidateRetriever implementations. BruteForceRetriever built in Task 8.

AnnRetriever is a documented stub only — it is the scaling path (vector DB as a coarse
top-K pre-filter, with the Scorer re-ranking exactly). See RATIONALE ADR-006. It is not
built for the prototype.
"""

from __future__ import annotations

from ..interfaces import CandidateRetriever, ItemRepository
from ..models import Item, OrgScope


class BruteForceRetriever(CandidateRetriever):
    """Loads all org-scoped opposing-type candidates from the repository.

    Exact and sufficient at prototype scale (~200 items). Delegates the actual query to
    the ItemRepository (which uses the by-type / by-org-type GSIs); this class exists to
    keep "which candidates" separate from "how to score" so an AnnRetriever can replace
    it without touching the Scorer (RATIONALE ADR-006).
    """

    def __init__(self, repository: ItemRepository) -> None:
        self._repository = repository

    def retrieve(self, query_item: Item, org_scope: OrgScope) -> list[Item]:
        return self._repository.list_candidates(query_item, org_scope)


class AnnRetriever(CandidateRetriever):
    """Future: approximate-nearest-neighbour retrieval backed by a vector index.

    Would return a coarse top-K by vector distance; the Scorer then re-ranks with the
    location/time terms. Intentionally NOT implemented for the prototype (RATIONALE
    ADR-006). Present so the swap is a localised change guarded by the RETRIEVER env var.
    """

    def retrieve(self, query_item: Item, org_scope: OrgScope) -> list[Item]:
        raise NotImplementedError(
            "AnnRetriever is a documented scaling stub — not built for the prototype "
            "(see RATIONALE ADR-006)."
        )
