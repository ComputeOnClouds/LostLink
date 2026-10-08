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
_DESCRIPTION_SOURCES = {"user", "ai", "ai_edited", "unknown"}


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
    photo_error = _validate_new_photo(principal, photo_key)
    if photo_error:
        return photo_error

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
        description_source=_description_source(body, description),
        description_photo_key=body.get("descriptionPhotoKey"),
        description_generated_at=body.get("descriptionGeneratedAt"),
        revision=1,
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
    item, stored = _load_in_org(principal, item_id, include_raw=True)
    if item.status != "available":
        return error(409, "Only available items can be edited. Use the claim actions for reserved or closed items.")

    expected_revision = int(body.get("revision", item.revision))
    old = (
        item.description, item.location_zone, item.event_time, item.photo_key,
        item.description_source, item.description_photo_key,
    )

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
        item.photo_key = body["photoKey"] or None

    description_changed = item.description != old[0]
    photo_changed = item.photo_key != old[3]
    if photo_changed:
        photo_error = _validate_new_photo(principal, item.photo_key)
        if photo_error:
            return photo_error
    if (
        photo_changed
        and item.photo_key
        and not description_changed
        and item.description_source in {"ai", "ai_edited"}
        and item.description_photo_key == old[3]
        and not body.get("confirmKeepDescription")
    ):
        return error(409, "Confirm that the existing generated description still matches the new photo, or generate a replacement.")
    if "descriptionSource" in body:
        requested_source = body.get("descriptionSource")
        if requested_source not in _DESCRIPTION_SOURCES:
            return error(400, "Invalid descriptionSource.")
        item.description_source = requested_source
    elif description_changed:
        item.description_source = "ai_edited" if old[4] in {"ai", "ai_edited"} else "user"
    if "descriptionPhotoKey" in body:
        item.description_photo_key = body.get("descriptionPhotoKey")
    if "descriptionGeneratedAt" in body:
        item.description_generated_at = body.get("descriptionGeneratedAt")

    if not item.description and not item.photo_key:
        return error(400, "Item must have a description or a photo.")

    changed = old != (
        item.description, item.location_zone, item.event_time, item.photo_key,
        item.description_source, item.description_photo_key,
    )
    if not changed:
        view = _public_view(item)
        view["rematching"] = False
        return respond(200, view)
    if description_changed:
        item.vectors = VectorMap()
    relevant_changed = any((description_changed, photo_changed, item.location_zone != old[1], item.event_time != old[2]))
    item.revision += 1
    ddb_item = item_to_ddb(item, created_at=stored.get("createdAt"))
    ddb_item["updatedAt"] = now_iso()
    try:
        _items().put_item(
            Item=ddb_item,
            ConditionExpression="attribute_not_exists(revision) OR revision = :expected",
            ExpressionAttributeValues={":expected": expected_revision},
        )
    except Exception as exc:
        if _is_conflict(exc):
            return error(409, "This item changed in another session. Reload it before saving.")
        raise
    if relevant_changed:
        _enqueue_match(item.item_id, item.item_type.value)
    view = _public_view(item)
    view["rematching"] = relevant_changed
    return respond(200, view)


def _withdraw_item(principal, item_id) -> dict:
    principal.require_staff()
    item, stored = _load_in_org(principal, item_id, include_raw=True)
    if item.status == "withdrawn":
        return respond(200, {"itemId": item.item_id, "status": item.status, "claimsAffected": 0})
    expected_revision = item.revision
    item.status = "withdrawn"
    item.revision += 1
    ddb_item = item_to_ddb(item, created_at=stored.get("createdAt"))
    ddb_item["updatedAt"] = now_iso()
    try:
        _items().put_item(
            Item=ddb_item,
            ConditionExpression="attribute_not_exists(revision) OR revision = :expected",
            ExpressionAttributeValues={":expected": expected_revision},
        )
    except Exception as exc:
        if _is_conflict(exc):
            return error(409, "This item changed in another session. Refresh before withdrawing it.")
        raise

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
    key = s3urls.new_photo_key(f"uploads/{principal.user_id}", reserved_item_id, content_type)
    url = s3urls.presign_put(key, content_type)
    return respond(200, {"uploadUrl": url, "photoKey": key})


# ---- helpers ------------------------------------------------------------------------


def org_type_key_str(org: str, type_str: str) -> str:
    return f"{org}#{type_str}"


def _load_in_org(principal, item_id, include_raw=False):
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
    return (item, resp["Item"]) if include_raw else item


def _public_view(item) -> dict:
    return {
        "itemId": item.item_id,
        "type": item.item_type.value,
        "organisationId": item.organisation_id,
        "description": item.description,
        "locationZone": item.location_zone,
        "eventTime": item.event_time,
        "photoKey": item.photo_key,
        "photoUrl": s3urls.presign_get(item.photo_key) if item.photo_key else None,
        "status": item.status,
        "descriptionSource": item.description_source,
        "descriptionPhotoKey": item.description_photo_key,
        "descriptionGeneratedAt": item.description_generated_at,
        "revision": item.revision,
    }


def _description_source(body, description: str) -> str:
    requested = body.get("descriptionSource")
    if requested in _DESCRIPTION_SOURCES:
        return requested
    return "user" if description else "unknown"


def _validate_new_photo(principal, key) -> dict | None:
    if not key:
        return None
    if not isinstance(key, str) or not key.startswith(f"uploads/{principal.user_id}/"):
        return error(403, "The selected photo does not belong to this account.")
    try:
        meta = s3urls.head(key)
    except Exception:
        return error(400, "The uploaded photo could not be found. Upload it again.")
    if (meta.get("ContentType") or "").lower() not in _ALLOWED_CONTENT_TYPES:
        return error(400, "The uploaded photo has an unsupported type.")
    return None


def _is_conflict(exc: Exception) -> bool:
    return "ConditionalCheckFailed" in type(exc).__name__ or "ConditionalCheckFailed" in str(exc)


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
