"""Claims workflow handler.

Task 11 implements the INDIVIDUAL side; Task 12 adds the STAFF side (routes guarded by
role in the same handler). Routes (behind the Cognito JWT authorizer):

Individual:
    GET    /matches                     -> my match suggestions (found details HIDDEN)
    POST   /claims/uploads              -> presigned URL for an evidence photo
    POST   /claims                      -> submit a claim (ownership evidence) for a match
    GET    /claims                      -> my claims + status
    GET    /claims/{claimId}            -> one of my claims (details only once approved)
    POST   /claims/{claimId}/respond    -> answer a staff info request / add evidence
    POST   /claims/{claimId}/cancel     -> withdraw a claim

Privacy core: a lost-report owner sees that a partner organisation MAY hold their item
(match score + org id) but NOT the found item's description or photo, until staff approve
the claim (claim_state.details_visible). Enforced in every response here.
"""

from __future__ import annotations

import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boto3
from boto3.dynamodb.conditions import Key

from pipeline.impl.ddb_mapping import ddb_to_item, now_iso

from .auth import principal_from_event, AuthError
from .responses import respond, error, parse_body, route_key, path_param
from . import s3urls
from . import claim_state as cs

_ITEMS_TABLE = os.environ.get("ITEMS_TABLE")
_MATCHES_TABLE = os.environ.get("MATCHES_TABLE")
_CLAIMS_TABLE = os.environ.get("CLAIMS_TABLE")

_ddb = boto3.resource("dynamodb")
_ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp", "application/pdf"}


def _items():
    return _ddb.Table(_ITEMS_TABLE)


def _matches():
    return _ddb.Table(_MATCHES_TABLE)


def _claims():
    return _ddb.Table(_CLAIMS_TABLE)


# ---- individual: match suggestions --------------------------------------------------


def _list_matches(principal) -> dict:
    """My match suggestions: matches whose lost report I own. Found details hidden."""
    principal.require_individual()

    # Find my lost reports (by-owner GSI), then gather their matches.
    reports = _items().query(
        IndexName="by-owner",
        KeyConditionExpression=Key("ownerId").eq(principal.user_id),
    ).get("Items", [])
    my_report_ids = {r["itemId"] for r in reports if r.get("itemType") == "lost"}

    suggestions = []
    for rid in my_report_ids:
        rows = _matches().query(
            KeyConditionExpression=Key("queryItemId").eq(rid),
        ).get("Items", [])
        for m in rows:
            suggestions.append({
                "queryItemId": m["queryItemId"],
                "candidateItemId": m["candidateItemId"],  # opaque handle for claiming
                "organisationId": m["organisationId"],
                "score": m.get("score"),
                # Deliberately NO description/photo of the found item (privacy).
                "message": "A partner organisation may be holding an item matching this report.",
            })
    return respond(200, {"matches": suggestions})


# ---- individual: claims -------------------------------------------------------------


def _create_upload_url(principal, body) -> dict:
    principal.require_individual()
    content_type = body.get("contentType")
    if content_type not in _ALLOWED_CONTENT_TYPES:
        return error(400, f"contentType must be one of {sorted(_ALLOWED_CONTENT_TYPES)}.")
    key = s3urls.new_photo_key(f"evidence/{principal.user_id}", uuid.uuid4().hex, content_type)
    return respond(200, {"uploadUrl": s3urls.presign_put(key, content_type), "evidenceKey": key})


def _create_claim(principal, body) -> dict:
    principal.require_individual()
    query_item_id = body.get("queryItemId")
    candidate_item_id = body.get("candidateItemId")
    evidence_text = (body.get("evidenceText") or "").strip()
    evidence_keys = body.get("evidenceKeys") or []

    if not query_item_id or not candidate_item_id:
        return error(400, "queryItemId and candidateItemId are required.")
    if not evidence_text and not evidence_keys:
        return error(400, "Provide ownership evidence (text and/or an uploaded file).")

    # The lost report must be mine, and the match must exist (prevents claiming arbitrary
    # found items — the claimant only ever references a match surfaced to them).
    report = _items().get_item(Key={"itemId": query_item_id}).get("Item")
    if not report or report.get("ownerId") != principal.user_id or report.get("itemType") != "lost":
        raise AuthError(403, "You can only claim against your own report.")
    match = _matches().get_item(
        Key={"queryItemId": query_item_id, "candidateItemId": candidate_item_id}
    ).get("Item")
    if not match:
        raise AuthError(404, "No such match suggestion.")

    claim_id = f"claim-{uuid.uuid4().hex}"
    now = now_iso()
    item = {
        "claimId": claim_id,
        "claimantId": principal.user_id,
        "claimantEmail": principal.email,
        "queryItemId": query_item_id,
        "candidateItemId": candidate_item_id,
        "organisationId": match["organisationId"],
        "state": cs.STATE_SUBMITTED,
        "evidenceText": evidence_text or None,
        "evidenceKeys": evidence_keys,
        "messages": [],
        "createdAt": now,
        "updatedAt": now,
    }
    _claims().put_item(Item=item)
    return respond(201, {"claimId": claim_id, "state": item["state"]})


def _list_claims(principal) -> dict:
    principal.require_individual()
    rows = _claims().query(
        IndexName="by-owner",
        KeyConditionExpression=Key("claimantId").eq(principal.user_id),
    ).get("Items", [])
    return respond(200, {"claims": [_claim_view(c) for c in rows]})


def _get_claim(principal, claim_id) -> dict:
    principal.require_individual()
    claim = _load_own_claim(principal, claim_id)
    return respond(200, _claim_view(claim, detailed=True))


def _respond_claim(principal, claim_id, body) -> dict:
    principal.require_individual()
    claim = _load_own_claim(principal, claim_id)
    try:
        new_state = cs.next_state("respond", claim["state"])
    except cs.InvalidTransition as e:
        return error(409, str(e))

    text = (body.get("message") or "").strip()
    new_keys = body.get("evidenceKeys") or []
    messages = claim.get("messages", [])
    if text:
        messages.append({"from": "claimant", "text": text, "at": now_iso()})

    _claims().update_item(
        Key={"claimId": claim_id},
        UpdateExpression="SET #s = :s, messages = :m, evidenceKeys = list_append(if_not_exists(evidenceKeys, :empty), :nk), updatedAt = :u",
        ExpressionAttributeNames={"#s": "state"},
        ExpressionAttributeValues={
            ":s": new_state, ":m": messages, ":nk": new_keys, ":empty": [], ":u": now_iso(),
        },
    )
    return respond(200, {"claimId": claim_id, "state": new_state})


def _cancel_claim(principal, claim_id) -> dict:
    principal.require_individual()
    claim = _load_own_claim(principal, claim_id)
    try:
        new_state = cs.next_state("cancel", claim["state"])
    except cs.InvalidTransition as e:
        return error(409, str(e))
    _claims().update_item(
        Key={"claimId": claim_id},
        UpdateExpression="SET #s = :s, updatedAt = :u",
        ExpressionAttributeNames={"#s": "state"},
        ExpressionAttributeValues={":s": new_state, ":u": now_iso()},
    )
    return respond(200, {"claimId": claim_id, "state": new_state})


# ---- helpers ------------------------------------------------------------------------


# ---- staff: claim review + decisions (Task 12) --------------------------------------


def _list_org_claims(principal) -> dict:
    """Claims against the caller's organisation (staff can see full evidence)."""
    principal.require_staff()
    rows = _claims().query(
        IndexName="by-org-type",
        KeyConditionExpression=Key("organisationId").eq(principal.organisation_id),
    ).get("Items", [])
    return respond(200, {"claims": [_staff_claim_view(c) for c in rows]})


def _get_org_claim(principal, claim_id) -> dict:
    principal.require_staff()
    claim = _load_org_claim(principal, claim_id)
    return respond(200, _staff_claim_view(claim, detailed=True))


def _staff_transition(principal, claim_id, action, body) -> dict:
    """Apply a staff action (request_info/approve/reject/reserve/hand_over)."""
    principal.require_staff()
    claim = _load_org_claim(principal, claim_id)
    try:
        new_state = cs.next_state(action, claim["state"])
    except cs.InvalidTransition as e:
        return error(409, str(e))

    messages = claim.get("messages", [])
    note = (body.get("message") or "").strip()
    if note:
        messages.append({"from": "staff", "text": note, "at": now_iso()})

    _claims().update_item(
        Key={"claimId": claim_id},
        UpdateExpression="SET #s = :s, messages = :m, updatedAt = :u",
        ExpressionAttributeNames={"#s": "state"},
        ExpressionAttributeValues={":s": new_state, ":m": messages, ":u": now_iso()},
    )

    # Reflect approval lifecycle onto the found item's status so it isn't matched/claimed
    # by others once it's being handed to a verified owner.
    candidate_id = claim["candidateItemId"]
    if new_state == cs.STATE_RESERVED:
        _set_item_status(candidate_id, "reserved")
    elif new_state == cs.STATE_HANDED_OVER:
        _set_item_status(candidate_id, "closed")

    # Notify the claimant of the decision (privacy-safe: no item details in the message).
    _notify_claimant(claim, new_state)

    return respond(200, {"claimId": claim_id, "state": new_state})


def _set_item_status(item_id, status) -> None:
    try:
        _items().update_item(
            Key={"itemId": item_id},
            UpdateExpression="SET #s = :s",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": status},
        )
    except Exception as e:  # noqa: BLE001
        print(f"failed to set item {item_id} status={status}: {e!r}")


def _notify_claimant(claim, new_state) -> None:
    """Email the claimant about a claim decision. Best-effort; never blocks the API."""
    sender = os.environ.get("SENDER_EMAIL")
    recipient = claim.get("claimantEmail")
    # Skip if no verified-capable sender (placeholder ".example") or no valid recipient.
    if not sender or sender.endswith(".example") or not recipient or "@" not in recipient:
        return
    msgs = {
        cs.STATE_INFO_REQUESTED: "The organisation has asked for more information about your claim.",
        cs.STATE_APPROVED: "Good news — your ownership claim has been approved.",
        cs.STATE_REJECTED: "Your ownership claim was not approved.",
        cs.STATE_RESERVED: "Your item has been reserved for collection.",
        cs.STATE_HANDED_OVER: "Your item has been handed over. Case closed.",
    }
    body = msgs.get(new_state)
    if not body:
        return
    try:
        import boto3

        boto3.client("ses").send_email(
            Source=sender,
            Destination={"ToAddresses": [recipient]},
            Message={
                "Subject": {"Data": "LostLink: an update on your claim"},
                "Body": {"Text": {"Data": body + "\n\n— LostLink"}},
            },
        )
    except Exception as e:  # noqa: BLE001
        print(f"claimant notification failed: {e!r}")


def notify_withdrawn_claims(organisation_id, candidate_item_id) -> int:
    """Called when a found item is withdrawn: reject active claims on it + notify.

    Exposed at module level so the staff inventory handler can call it on withdrawal.
    Returns the number of affected claims.
    """
    rows = _claims().query(
        IndexName="by-org-type",
        KeyConditionExpression=Key("organisationId").eq(organisation_id),
    ).get("Items", [])
    affected = 0
    for claim in rows:
        if claim.get("candidateItemId") != candidate_item_id:
            continue
        if claim.get("state") in cs.TERMINAL_STATES:
            continue
        _claims().update_item(
            Key={"claimId": claim["claimId"]},
            UpdateExpression="SET #s = :s, updatedAt = :u",
            ExpressionAttributeNames={"#s": "state"},
            ExpressionAttributeValues={":s": cs.STATE_REJECTED, ":u": now_iso()},
        )
        _notify_claimant(claim, cs.STATE_REJECTED)
        affected += 1
    return affected


def _load_org_claim(principal, claim_id):
    if not claim_id:
        raise AuthError(400, "Missing claim id.")
    claim = _claims().get_item(Key={"claimId": claim_id}).get("Item")
    if not claim:
        raise AuthError(404, "Claim not found.")
    if claim.get("organisationId") != principal.organisation_id:
        raise AuthError(403, "This claim is not against your organisation.")
    return claim


def _staff_claim_view(claim, detailed=False) -> dict:
    """Staff-facing view: staff see the claimant's evidence + their own found item."""
    view = {
        "claimId": claim["claimId"],
        "queryItemId": claim.get("queryItemId"),
        "candidateItemId": claim.get("candidateItemId"),
        "organisationId": claim.get("organisationId"),
        "state": claim.get("state"),
        "createdAt": claim.get("createdAt"),
        "updatedAt": claim.get("updatedAt"),
        "evidenceText": claim.get("evidenceText"),
        "evidenceKeys": claim.get("evidenceKeys", []),
    }
    if detailed:
        view["messages"] = claim.get("messages", [])
        found = _items().get_item(Key={"itemId": claim["candidateItemId"]}).get("Item")
        if found:
            view["item"] = {
                "description": found.get("description"),
                "locationZone": found.get("locationZone"),
                "photoKey": found.get("photoKey"),
                "status": found.get("status"),
            }
    return view


def _load_own_claim(principal, claim_id):
    if not claim_id:
        raise AuthError(400, "Missing claim id.")
    claim = _claims().get_item(Key={"claimId": claim_id}).get("Item")
    if not claim:
        raise AuthError(404, "Claim not found.")
    if claim.get("claimantId") != principal.user_id:
        raise AuthError(403, "You do not have access to this claim.")
    return claim


def _claim_view(claim, detailed=False) -> dict:
    """Claimant-facing view. Reveals found-item details only once approved onward."""
    state = claim.get("state")
    view = {
        "claimId": claim["claimId"],
        "queryItemId": claim.get("queryItemId"),
        "organisationId": claim.get("organisationId"),
        "state": state,
        "createdAt": claim.get("createdAt"),
        "updatedAt": claim.get("updatedAt"),
    }
    if detailed:
        view["evidenceText"] = claim.get("evidenceText")
        view["messages"] = claim.get("messages", [])

    if cs.details_visible(state):
        # Ownership verified — now safe to reveal the found item + collection info.
        found = _items().get_item(Key={"itemId": claim["candidateItemId"]}).get("Item")
        if found:
            view["item"] = {
                "description": found.get("description"),
                "locationZone": found.get("locationZone"),
                "photoKey": found.get("photoKey"),
                "status": found.get("status"),
            }
        view["collection"] = (
            "Your claim is approved. Please arrange collection with the organisation."
        )
    else:
        view["item"] = None  # hidden until approval (privacy core)
    return view


# ---- entry point --------------------------------------------------------------------


def handler(event, _context=None):
    try:
        principal = principal_from_event(event)
        rk = route_key(event)
        claim_id = path_param(event, "claimId")

        # Individual routes (Task 11).
        if rk == "GET /matches":
            return _list_matches(principal)
        if rk == "POST /claims/uploads":
            return _create_upload_url(principal, parse_body(event))
        if rk == "POST /claims":
            return _create_claim(principal, parse_body(event))
        if rk == "GET /claims":
            return _list_claims(principal)
        if rk == "GET /claims/{claimId}":
            return _get_claim(principal, claim_id)
        if rk == "POST /claims/{claimId}/respond":
            return _respond_claim(principal, claim_id, parse_body(event))
        if rk == "POST /claims/{claimId}/cancel":
            return _cancel_claim(principal, claim_id)

        # Staff routes (Task 12).
        if rk == "GET /org/claims":
            return _list_org_claims(principal)
        if rk == "GET /org/claims/{claimId}":
            return _get_org_claim(principal, claim_id)
        if rk == "POST /org/claims/{claimId}/request-info":
            return _staff_transition(principal, claim_id, "request_info", parse_body(event))
        if rk == "POST /org/claims/{claimId}/approve":
            return _staff_transition(principal, claim_id, "approve", parse_body(event))
        if rk == "POST /org/claims/{claimId}/reject":
            return _staff_transition(principal, claim_id, "reject", parse_body(event))
        if rk == "POST /org/claims/{claimId}/reserve":
            return _staff_transition(principal, claim_id, "reserve", parse_body(event))
        if rk == "POST /org/claims/{claimId}/handover":
            return _staff_transition(principal, claim_id, "hand_over", parse_body(event))

        return error(404, f"No route for {rk}.")
    except AuthError as e:
        return error(e.status, e.message)
    except Exception as e:  # noqa: BLE001
        print(f"ERROR handling claims request: {e!r}")
        return error(500, "Internal error.")
