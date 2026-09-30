"""Mapping between pipeline dataclasses and the DynamoDB item shape.

Kept separate from the repository so request Lambdas (Tasks 4/5) and the worker share
one canonical encoding. See RATIONALE ADR-012 for the table/key design.

Vectors are stored as JSON strings (compact and portable) rather than DynamoDB number
lists, which keeps item size small and avoids per-element type overhead. At prototype
scale (~1536-dim Titan text vectors) this is well within DynamoDB's 400KB item limit.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from ..models import Item, ItemType, VectorMap, MatchResult


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def org_type_key(organisation_id: str, item_type: ItemType) -> str:
    """Composite GSI partition key: "<orgId>#<type>" (see by-org-type GSI)."""
    return f"{organisation_id}#{item_type.value}"


def item_to_ddb(item: Item, created_at: str | None = None) -> dict[str, Any]:
    """Serialize an Item to a DynamoDB attribute map (boto3 resource-level dict)."""
    created = created_at or now_iso()
    ddb: dict[str, Any] = {
        "itemId": item.item_id,
        "itemType": item.item_type.value,
        "organisationId": item.organisation_id,
        "ownerId": item.owner_id,
        "status": item.status,
        "createdAt": created,
        # Derived key for the by-org-type GSI (staff inventory, org-scoped).
        "orgType": org_type_key(item.organisation_id, item.item_type),
    }
    if item.owner_email is not None:
        ddb["ownerEmail"] = item.owner_email
    if item.description is not None:
        ddb["description"] = item.description
    if item.location_zone is not None:
        ddb["locationZone"] = item.location_zone
    if item.event_time is not None:
        ddb["eventTime"] = item.event_time
    if item.photo_key is not None:
        ddb["photoKey"] = item.photo_key
    if item.vectors.has_text():
        ddb["vecText"] = json.dumps(item.vectors.text)
    if item.vectors.has_image():
        ddb["vecImage"] = json.dumps(item.vectors.image)
    return ddb


def ddb_to_item(ddb: dict[str, Any]) -> Item:
    """Deserialize a DynamoDB attribute map back into an Item."""
    vectors = VectorMap()
    if ddb.get("vecText"):
        vectors.text = json.loads(ddb["vecText"])
    if ddb.get("vecImage"):
        vectors.image = json.loads(ddb["vecImage"])
    return Item(
        item_id=ddb["itemId"],
        item_type=ItemType(ddb["itemType"]),
        organisation_id=ddb["organisationId"],
        owner_id=ddb["ownerId"],
        owner_email=ddb.get("ownerEmail"),
        description=ddb.get("description"),
        location_zone=ddb.get("locationZone"),
        event_time=ddb.get("eventTime"),
        photo_key=ddb.get("photoKey"),
        vectors=vectors,
        status=ddb.get("status", "pending_match"),
    )


def match_to_ddb(match: MatchResult, notified: bool = False) -> dict[str, Any]:
    """Serialize a MatchResult. The ``notified`` flag supports per-pair dedup (Task 10)."""
    return {
        "queryItemId": match.query_item_id,
        "candidateItemId": match.candidate_item_id,
        "organisationId": match.organisation_id,
        "score": _to_decimal_safe(match.score),
        "profileName": match.profile_name,
        "breakdown": {k: _to_decimal_safe(v) for k, v in match.breakdown.items()},
        "notified": notified,
        "createdAt": now_iso(),
    }


def _to_decimal_safe(value: float):
    """DynamoDB rejects float; store as Decimal via string to avoid binary drift."""
    from decimal import Decimal

    return Decimal(str(value))
