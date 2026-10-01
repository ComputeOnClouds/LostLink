"""LostLink matching pipeline.

The pipeline is composed of swappable stages, each defined as an abstract interface
with one (or more) concrete implementation. The matching worker depends only on the
interfaces; implementations are selected at runtime via environment variables. This is
what keeps scoring, retrieval, description generation, embedding, and notification
independently replaceable.

Stages:
    DescriptionSource  - produce an item's text (photo -> Claude, or typed text)
    Embedder           - produce a VectorMap for an item (text now; image reserved)
    CandidateRetriever - fetch org-scoped candidate items to compare against
    Scorer             - score a pair of items given a weight map (pure function)
    ProfileSelector    - choose the weight map + threshold for a pair
    Notifier           - notify a report owner of a match
    ItemRepository     - persistence boundary (hides DynamoDB)

See docs/ARCHITECTURE.md section 2 for the class-level interaction diagram and contracts.
"""

from .models import Item, ItemType, VectorMap, MatchResult, Profile, OrgScope
from .interfaces import (
    DescriptionSource,
    Embedder,
    CandidateRetriever,
    Scorer,
    ProfileSelector,
    Notifier,
    ItemRepository,
)

__all__ = [
    "Item",
    "ItemType",
    "VectorMap",
    "MatchResult",
    "Profile",
    "OrgScope",
    "DescriptionSource",
    "Embedder",
    "CandidateRetriever",
    "Scorer",
    "ProfileSelector",
    "Notifier",
    "ItemRepository",
]
