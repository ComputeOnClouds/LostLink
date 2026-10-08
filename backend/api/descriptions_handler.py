"""Authenticated, idempotent photo-to-description preview generation.

Generation is deliberately separate from report/item persistence: cancelling a preview
never mutates the saved record. The caller must either own the uploaded photo or have
role/org access to the item that references it.
"""

from __future__ import annotations

import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boto3

from pipeline.impl.ddb_mapping import ddb_to_item, now_iso
from pipeline.impl.description import ClaudeDescriptionSource
from pipeline.models import Item, ItemType

from .auth import principal_from_event, AuthError
from .responses import respond, error, parse_body, route_key
from . import s3urls

_ITEMS_TABLE = os.environ.get("ITEMS_TABLE")
_ddb = boto3.resource("dynamodb")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{8,100}$")
_IMAGE_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}


def _items():
    return _ddb.Table(_ITEMS_TABLE)


def _authorise_photo(principal, photo_key: str, item_id: str | None) -> None:
    # Newly uploaded, not-yet-saved photos are namespaced to the authenticated user.
    if photo_key.startswith(f"uploads/{principal.user_id}/"):
        return
    if not item_id:
        raise AuthError(403, "This photo is not available for description generation.")
    row = _items().get_item(Key={"itemId": item_id}).get("Item")
    if not row or row.get("photoKey") != photo_key:
        raise AuthError(404, "Photo not found.")
    item = ddb_to_item(row)
    if principal.is_individual:
        if item.item_type is not ItemType.LOST or item.owner_id != principal.user_id:
            raise AuthError(403, "You do not have access to this photo.")
    elif principal.is_staff:
        if item.item_type is not ItemType.FOUND or item.organisation_id != principal.organisation_id:
            raise AuthError(403, "You do not have access to this photo.")
    else:
        raise AuthError(403, "Your account cannot generate item descriptions.")


def _generate(principal, body) -> dict:
    photo_key = str(body.get("photoKey") or "")
    request_id = str(body.get("requestId") or "")
    item_id = body.get("itemId")
    if not photo_key or not _REQUEST_ID.match(request_id):
        return error(400, "photoKey and a valid requestId are required.")

    _authorise_photo(principal, photo_key, item_id)
    try:
        meta = s3urls.head(photo_key)
    except Exception:
        return error(400, "The uploaded photo could not be found.")
    if (meta.get("ContentType") or "").lower() not in _IMAGE_TYPES:
        return error(400, "Descriptions can only be generated from JPEG, PNG or WebP images.")

    marker_id = f"description-request#{principal.user_id}#{request_id}"
    existing = _items().get_item(Key={"itemId": marker_id}, ConsistentRead=True).get("Item")
    if existing and existing.get("status") == "complete":
        return respond(200, existing["result"])
    if existing:
        return error(409, "Description generation is already in progress for this request.")

    now = now_iso()
    try:
        _items().put_item(
            Item={
                "itemId": marker_id,
                "recordType": "description_request",
                "requestOwnerId": principal.user_id,
                "status": "in_progress",
                "createdAt": now,
                "expiresAt": int(time.time()) + 24 * 60 * 60,
            },
            ConditionExpression="attribute_not_exists(itemId)",
        )
    except Exception as exc:
        if "ConditionalCheckFailed" in type(exc).__name__ or "ConditionalCheckFailed" in str(exc):
            return error(409, "Description generation is already in progress for this request.")
        raise

    try:
        draft = ClaudeDescriptionSource().describe(
            Item(
                item_id=item_id or "preview",
                item_type=ItemType.LOST,
                organisation_id=principal.organisation_id or "individual",
                owner_id=principal.user_id,
                photo_key=photo_key,
            )
        )
        if not draft:
            raise RuntimeError("The model returned an empty description")
        result = {
            "description": draft,
            "descriptionSource": "ai",
            "descriptionPhotoKey": photo_key,
            "descriptionGeneratedAt": now_iso(),
            "requestId": request_id,
        }
        _items().update_item(
            Key={"itemId": marker_id},
            UpdateExpression="SET #s = :s, #result = :r, updatedAt = :u",
            ExpressionAttributeNames={"#s": "status", "#result": "result"},
            ExpressionAttributeValues={":s": "complete", ":r": result, ":u": now_iso()},
        )
        return respond(200, result)
    except Exception:
        # A failed request id may be retried intentionally; remove only its marker.
        _items().delete_item(Key={"itemId": marker_id})
        raise


def handler(event, _context=None):
    try:
        principal = principal_from_event(event)
        if route_key(event) == "POST /descriptions/generate":
            return _generate(principal, parse_body(event))
        return error(404, f"No route for {route_key(event)}.")
    except AuthError as exc:
        return error(exc.status, exc.message)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR generating description: {exc!r}")
        return error(502, "Description generation failed. Keep the photo and try again, or type a description.")
