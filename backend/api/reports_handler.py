"""Individual lost-item reporting handler (Task 4).

Routes (behind the Cognito JWT authorizer):
    POST   /uploads            -> presigned S3 PUT url for a photo (before creating)
    POST   /reports            -> create a lost report
    GET    /reports            -> list the caller's own reports
    GET    /reports/{itemId}   -> get one of the caller's reports
    PATCH  /reports/{itemId}   -> edit one of the caller's reports
    DELETE /reports/{itemId}   -> withdraw one of the caller's reports

Ownership rule: an individual may only read/modify reports whose ownerId == their token
sub. Cross-user access returns 403. Text + location are mandatory; a photo is optional.

On create/edit, a match job is enqueued to SQS if MATCH_QUEUE_URL is set (wired in
Task 8); until then the report is simply persisted.
"""

from __future__ import annotations

import os
import sys
import json
import uuid

# The pipeline package lives alongside this one in the deployment bundle.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boto3

from pipeline.models import Item, ItemType, VectorMap
from pipeline.impl.ddb_mapping import item_to_ddb, ddb_to_item, now_iso

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


def _create_report(principal, body) -> dict:
    principal.require_individual()

    description = (body.get("description") or "").strip()
    location_zone = (body.get("locationZone") or "").strip()
    photo_key = body.get("photoKey")  # optional; from a prior /uploads call

    # Text + location are mandatory. Description may be empty ONLY if a photo is present
    # (a description will be generated from the photo by the pipeline in Task 7).
    if not location_zone:
        return error(400, "locationZone is required.")
    if not description and not photo_key:
        return error(400, "Provide a description, or a photo to generate one from.")

    item = Item(
        item_id=f"lost-{uuid.uuid4().hex}",
        item_type=ItemType.LOST,
        # For an individual the "organisation" is where the loss occurred / their zone.
        # We record it as the location zone context; matching is cross-org regardless.
        organisation_id=body.get("organisationId") or "individual",
        owner_id=principal.user_id,
        owner_email=principal.email,
        description=description or None,
        location_zone=location_zone,
        event_time=body.get("eventTime") or now_iso(),
        photo_key=photo_key,
        vectors=VectorMap(),  # embeddings populated by the worker (Task 7/8)
        status="pending_match",
    )
    _items().put_item(Item=item_to_ddb(item))
    _enqueue_match(item.item_id, item.item_type.value)
    return respond(201, {"itemId": item.item_id, "status": item.status})


def _list_reports(principal) -> dict:
    principal.require_individual()
    resp = _items().query(
        IndexName="by-owner",
        KeyConditionExpression="ownerId = :o",
        ExpressionAttributeValues={":o": principal.user_id},
        ScanIndexForward=False,  # newest first
    )
    items = [ddb_to_item(i) for i in resp.get("Items", [])]
    return respond(200, {"reports": [_public_view(i) for i in items]})


def _get_report(principal, item_id) -> dict:
    principal.require_individual()
    item = _load_owned(principal, item_id)
    return respond(200, _public_view(item))


def _edit_report(principal, item_id, body) -> dict:
    principal.require_individual()
    item = _load_owned(principal, item_id)

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

    if not item.description and not item.photo_key:
        return error(400, "Report must have a description or a photo.")

    # Editing invalidates prior embeddings; clear so the worker recomputes.
    item.vectors = VectorMap()
    item.status = "pending_match"
    _items().put_item(Item=item_to_ddb(item))
    _enqueue_match(item.item_id, item.item_type.value)
    return respond(200, _public_view(item))


def _withdraw_report(principal, item_id) -> dict:
    principal.require_individual()
    item = _load_owned(principal, item_id)
    item.status = "withdrawn"
    _items().put_item(Item=item_to_ddb(item))
    return respond(200, {"itemId": item.item_id, "status": item.status})


def _create_upload_url(principal, body) -> dict:
    principal.require_individual()
    content_type = body.get("contentType")
    if content_type not in _ALLOWED_CONTENT_TYPES:
        return error(400, f"contentType must be one of {sorted(_ALLOWED_CONTENT_TYPES)}.")
    # Reserve an item id so the photo key is tied to the eventual report.
    reserved_item_id = f"lost-{uuid.uuid4().hex}"
    key = s3urls.new_photo_key("individual", reserved_item_id, content_type)
    url = s3urls.presign_put(key, content_type)
    return respond(200, {"uploadUrl": url, "photoKey": key})


# ---- helpers ------------------------------------------------------------------------


def _load_owned(principal, item_id):
    if not item_id:
        raise AuthError(400, "Missing item id.")
    resp = _items().get_item(Key={"itemId": item_id})
    if "Item" not in resp:
        raise AuthError(404, "Report not found.")
    item = ddb_to_item(resp["Item"])
    if item.owner_id != principal.user_id:
        # Do not leak existence of other users' reports.
        raise AuthError(403, "You do not have access to this report.")
    if item.item_type is not ItemType.LOST:
        raise AuthError(404, "Report not found.")
    return item


def _public_view(item) -> dict:
    return {
        "itemId": item.item_id,
        "type": item.item_type.value,
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

        if rk == "POST /uploads":
            return _create_upload_url(principal, parse_body(event))
        if rk == "POST /reports":
            return _create_report(principal, parse_body(event))
        if rk == "GET /reports":
            return _list_reports(principal)
        if rk == "GET /reports/{itemId}":
            return _get_report(principal, item_id)
        if rk == "PATCH /reports/{itemId}":
            return _edit_report(principal, item_id, parse_body(event))
        if rk == "DELETE /reports/{itemId}":
            return _withdraw_report(principal, item_id)

        return error(404, f"No route for {rk}.")
    except AuthError as e:
        return error(e.status, e.message)
    except Exception as e:  # noqa: BLE001 — surface a safe message, log detail
        print(f"ERROR handling request: {e!r}")
        return error(500, "Internal error.")
