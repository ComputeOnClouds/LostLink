"""Shared data models for the matching pipeline.

These are plain, dependency-free dataclasses so the pure stages (notably the Scorer)
can be imported and exercised by the evaluation harness without any AWS SDK present.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ItemType(str, Enum):
    """Whether an item is a user's lost report or an organisation's found item."""

    LOST = "lost"
    FOUND = "found"

    @property
    def opposing(self) -> "ItemType":
        """The type we match against (lost <-> found)."""
        return ItemType.FOUND if self is ItemType.LOST else ItemType.LOST


# ---- item status values -------------------------------------------------------------
# A LOST report moves through a small lifecycle driven by the matching worker:
#   PENDING_MATCH : created, not yet processed by the worker ("searching").
#   MATCHED       : the worker found >=1 found-item above the score threshold.
#   NO_MATCH      : the worker ran and found nothing above the threshold yet.
#   WITHDRAWN     : the user withdrew the report.
# (A report can cycle PENDING_MATCH -> MATCHED/NO_MATCH again if it is edited or if new
# found items arrive and it is re-processed.)
STATUS_PENDING_MATCH = "pending_match"
STATUS_MATCHED = "matched"
STATUS_NO_MATCH = "no_match"
STATUS_WITHDRAWN = "withdrawn"

# A FOUND item's lifecycle is driven by staff + the claims flow:
#   AVAILABLE : registered and matchable.
#   RESERVED  : an approved claimant is collecting it.
#   CLOSED    : handed over.
#   WITHDRAWN : staff removed it.
STATUS_AVAILABLE = "available"
STATUS_RESERVED = "reserved"
STATUS_CLOSED = "closed"

# Statuses that take an item out of matching (neither matched against nor re-matched).
INACTIVE_STATUSES = {STATUS_WITHDRAWN, STATUS_RESERVED, STATUS_CLOSED}


@dataclass
class VectorMap:
    """Named embedding vectors for an item.

    Today only ``text`` is populated. ``image`` is reserved so that image embeddings
    (Option 2, see RATIONALE ADR-003) can be enabled later by populating this slot and
    raising ``w_image`` in the scorer weights — no other class needs to change.
    """

    text: Optional[list[float]] = None
    image: Optional[list[float]] = None

    def has_text(self) -> bool:
        return self.text is not None and len(self.text) > 0

    def has_image(self) -> bool:
        return self.image is not None and len(self.image) > 0


@dataclass
class ItemLocation:
    """User-confirmed WGS84 point; display labels never determine distance."""

    name: str
    latitude: float
    longitude: float
    address: Optional[str] = None
    provider: str = "manual"
    selection_method: str = "map"
    provider_place_id: Optional[str] = None
    note: Optional[str] = None


@dataclass
class Item:
    """A lost report or a found item, as seen by the pipeline.

    Storage-specific concerns live behind ItemRepository; this is the in-memory shape
    the pipeline stages operate on.
    """

    item_id: str
    item_type: ItemType
    organisation_id: str
    owner_id: str  # individual user id (lost) or the registering staff id (found)
    owner_email: Optional[str] = None  # for notifications (set at report/item creation)
    description: Optional[str] = None
    location_zone: Optional[str] = None  # fixed zone id (see RATIONALE ADR-007)
    event_time: Optional[str] = None  # ISO 8601 timestamp of loss/find
    photo_key: Optional[str] = None  # S3 object key, or None if no photo
    vectors: VectorMap = field(default_factory=VectorMap)
    status: str = "pending_match"
    # Description provenance is intentionally separate from the user-visible text.  Old
    # rows deserialize as ``unknown``; the UI disclosure does not depend on this field.
    description_source: str = "unknown"  # user | ai | ai_edited | unknown
    description_photo_key: Optional[str] = None
    description_generated_at: Optional[str] = None
    # User/API revision. Async enrichment may save against this value but must never
    # overwrite a row whose revision has moved on.
    revision: int = 0
    location: Optional[ItemLocation] = None
    search_radius_metres: Optional[int] = None  # lost reports only; None = any distance


@dataclass
class Profile:
    """A scoring profile: the weight map plus the notification threshold to apply.

    ``weights`` keys: ``text``, ``image``, ``location``, ``time``.
    """

    name: str
    weights: dict[str, float]
    threshold: float


@dataclass
class MatchResult:
    """The outcome of scoring a query item against one candidate."""

    query_item_id: str
    candidate_item_id: str
    organisation_id: str  # org holding the found item
    score: float
    profile_name: str
    breakdown: dict[str, float] = field(default_factory=dict)


@dataclass
class OrgScope:
    """Which organisations' inventories a retrieval is authorised to search.

    ``all_authorised`` reflects the cross-organisation matching model: a lost report is
    matched against found items across every participating organisation. ``org_ids``
    may narrow this (e.g. staff-side queries limited to their own org).
    """

    all_authorised: bool = True
    org_ids: Optional[list[str]] = None
