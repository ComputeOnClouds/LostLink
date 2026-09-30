"""Staff inventory management handler (Task 5).

Routes (behind the Cognito JWT authorizer; caller must be in the Staff group):
    POST   /items/uploads      -> presigned S3 PUT url for a found-item photo
    POST   /items              -> register a found item (photo-first; desc optional)
    GET    /items              -> list/search the caller's ORG inventory
    GET    /items/{itemId}     -> get one found item (must belong to caller's org)
    PATCH  /items/{itemId}     -> update a found item in the caller's org
    DELETE /items/{itemId}     -> withdraw a found item in the caller's org

Org boundary: a found item's organisationId is taken from the caller's token
(`custom:organisationId`), never from the request. Reads/updates require the item's
organisationId to equal the caller's org, otherwise 403 — this is the privacy core
that keeps one organisation's inventory invisible to another.

Search: optional `?q=` substring filter over the description, and `?status=` filter,
applied over the org-scoped result set.
"""

from __future__ import annotations

import os
import sys
import json
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boto3

from pipeline.models import Item, ItemType, VectorMap
from pipeline.impl.ddb_mapping import item_to_ddb, ddb_to_item, now_iso, org_type_key

from .auth import principal_from_event, AuthError
from .responses import respond, error, parse_body, route_key, path_param
from . import s3urls

_ITEMS_TABLE = os.environ.get("ITEMS_TABLE")
_MATCH_QUEUE_URL = os.environ.get("MATCH_QUEUE_URL")  # optional until Task 8

_ddb = boto3.resource("dynamodb")
_sqs = boto3.client("sqs") if _MATCH_QUEUE_URL else None

_ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}


def _items():
    return _ddb.Table(_ITEMS_TABLE)


def _enqueue_match(item_id: str, item_type: str) -> None:
    if _sqs and _MATCH_QUEUE_URL:
        _sqs.send_message(
            QueueUrl=_MATCH_QUEUE_URL,
            MessageBody=json.dumps({"itemId": item_id, "type": item_type}),
        )


# ---- route handlers -----------------------------------------------------------------


def _register_found(principal, body) -> dict:
    principal.require_staff()
    org = principal.organisation_id

    description = (body.get("description") or "").strip()
    location_zone = (body.get("locationZone") or "").strip()
    photo_key = body.get("photoKey")  # optional; from a prior /items/uploads call

    if not location_zone:
        return error(400, "locationZone is required.")
    # Photo-first: a description may be omitted if a photo is supplied (the pipeline
    # generates one from the photo in Task 7). Otherwise a description is required.
    if not description and not photo_key:
        return error(400, "Provide a description, or a photo to generate one from.")

    item = Item(
        item_id=f"found-{uuid.uuid4().hex}",
        item_type=ItemType.FOUND,
        organisation_id=org,  # from the token, NEVER the body
        owner_id=principal.user_id,  # the staff who registered it
        owner_email=principal.email,
        description=description or None,
        location_zone=location_zone,
        event_time=body.get("eventTime") or now_iso(),
        photo_key=photo_key,
        vectors=VectorMap(),
        status="available",
    )
    _items().put_item(Item=item_to_ddb(item))
    _enqueue_match(item.item_id, item.item_type.value)
    return respond(201, {"itemId": item.item_id, "status": item.status})


def _list_inventory(principal, event) -> dict:
    principal.require_staff()
    org = principal.organisation_id
    resp = _items().query(
        IndexName="by-org-type",
        KeyConditionExpression="orgType = :ot",
        ExpressionAttributeValues={":ot": org_type_key_str(org, "found")},
        ScanIndexForward=False,
    )
    items = [ddb_to_item(i) for i in resp.get("Items", [])]

    params = event.get("queryStringParameters") or {}
    q = (params.get("q") or "").strip().lower()
    status = (params.get("status") or "").strip().lower()
    if q:
        items = [i for i in items if i.description and q in i.description.lower()]
    if status:
        items = [i for i in items if i.status.lower() == status]

    return respond(200, {"items": [_public_view(i) for i in items]})


def _get_item(principal, item_id) -> dict:
    principal.require_staff()
    item = _load_in_org(principal, item_id)
    return respond(200, _public_view(item))


def _update_item(principal, item_id, body) -> dict:
    principal.require_staff()
    item = _load_in_org(principal, item_id)

    if "description" in body:
        item.description = (body["description"] or "").strip() or None
    if "locationZone" in body:
        lz = (body["locationZone"] or "").strip()
        if not lz:
            return error(400, "locationZone cannot be empty.")
        item.location_zone = lz
    if "eventTime" in body:
        item.event_time = body["eventTime"]
    if "photoKey" in body:
        item.photo_key = body["photoKey"]
    if "status" in body:
        item.status = (body["status"] or "").strip() or item.status

    if not item.description and not item.photo_key:
        return error(400, "Item must have a description or a photo.")

    # Content changes invalidate embeddings; recompute via the worker.
    item.vectors = VectorMap()
    _items().put_item(Item=item_to_ddb(item))
    _enqueue_match(item.item_id, item.item_type.value)
    return respond(200, _public_view(item))


def _withdraw_item(principal, item_id) -> dict:
    principal.require_staff()
    item = _load_in_org(principal, item_id)
    item.status = "withdrawn"
    _items().put_item(Item=item_to_ddb(item))

    # Reject + notify any active claimants on this now-unavailable item (best-effort).
    affected = 0
    try:
        from .claims_handler import notify_withdrawn_claims

        affected = notify_withdrawn_claims(item.organisation_id, item.item_id)
    except Exception as e:  # noqa: BLE001
        print(f"withdraw: notifying claimants failed: {e!r}")

    return respond(200, {"itemId": item.item_id, "status": item.status, "claimsAffected": affected})


def _create_upload_url(principal, body) -> dict:
    principal.require_staff()
    org = principal.organisation_id
    content_type = body.get("contentType")
    if content_type not in _ALLOWED_CONTENT_TYPES:
        return error(400, f"contentType must be one of {sorted(_ALLOWED_CONTENT_TYPES)}.")
    reserved_item_id = f"found-{uuid.uuid4().hex}"
    key = s3urls.new_photo_key(org, reserved_item_id, content_type)
    url = s3urls.presign_put(key, content_type)
    return respond(200, {"uploadUrl": url, "photoKey": key})


# ---- helpers ------------------------------------------------------------------------


def org_type_key_str(org: str, type_str: str) -> str:
    return f"{org}#{type_str}"


def _load_in_org(principal, item_id):
    if not item_id:
        raise AuthError(400, "Missing item id.")
    resp = _items().get_item(Key={"itemId": item_id})
    if "Item" not in resp:
        raise AuthError(404, "Item not found.")
    item = ddb_to_item(resp["Item"])
    if item.item_type is not ItemType.FOUND:
        raise AuthError(404, "Item not found.")
    # Org boundary: staff may only touch items in their own organisation.
    if item.organisation_id != principal.organisation_id:
        raise AuthError(403, "You do not have access to this item.")
    return item


def _public_view(item) -> dict:
    return {
        "itemId": item.item_id,
        "type": item.item_type.value,
        "organisationId": item.organisation_id,
        "description": item.description,
        "locationZone": item.location_zone,
        "eventTime": item.event_time,
        "photoKey": item.photo_key,
        "status": item.status,
    }


# ---- entry point --------------------------------------------------------------------


def handler(event, _context=None):
    try:
        principal = principal_from_event(event)
        rk = route_key(event)
        item_id = path_param(event, "itemId")

        if rk == "POST /items/uploads":
            return _create_upload_url(principal, parse_body(event))
        if rk == "POST /items":
            return _register_found(principal, parse_body(event))
        if rk == "GET /items":
            return _list_inventory(principal, event)
        if rk == "GET /items/{itemId}":
            return _get_item(principal, item_id)
        if rk == "PATCH /items/{itemId}":
            return _update_item(principal, item_id, parse_body(event))
        if rk == "DELETE /items/{itemId}":
            return _withdraw_item(principal, item_id)

        return error(404, f"No route for {rk}.")
    except AuthError as e:
        return error(e.status, e.message)
    except Exception as e:  # noqa: BLE001
        print(f"ERROR handling request: {e!r}")
        return error(500, "Internal error.")
