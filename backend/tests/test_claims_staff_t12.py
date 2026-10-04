"""Task 12 unit tests for staff claim transitions + withdrawal notifications.

Exercises _staff_transition, _load_org_claim org boundary, item-status side effects, and
notify_withdrawn_claims, using in-memory fakes injected into the module's table getters.
"""

import os
import types

import pytest


os.environ.setdefault("ITEMS_TABLE", "T")
os.environ.setdefault("MATCHES_TABLE", "T")
os.environ.setdefault("CLAIMS_TABLE", "T")

from api import claims_handler as ch  # noqa: E402
from api import claim_state as cs  # noqa: E402
from api.auth import Principal, AuthError  # noqa: E402


class FakeTable:
    def __init__(self, rows=None):
        self.rows = rows or {}  # key-tuple -> item
        self.updates = []

    def get_item(self, Key=None):
        # single-key tables here (claimId or itemId)
        k = tuple(sorted(Key.items()))
        return {"Item": self.rows[k]} if k in self.rows else {}

    def query(self, IndexName=None, KeyConditionExpression=None):
        # return all rows (tests filter by organisationId in the handler)
        return {"Items": list(self.rows.values())}

    def update_item(self, Key=None, UpdateExpression=None, ExpressionAttributeNames=None,
                    ExpressionAttributeValues=None, ConditionExpression=None):
        self.updates.append((Key, ExpressionAttributeValues))
        k = tuple(sorted(Key.items()))
        row = self.rows.setdefault(k, dict(Key))
        # apply SET #s = :s and status
        vals = ExpressionAttributeValues or {}
        if ":s" in vals:
            # figure out target attr from names
            names = ExpressionAttributeNames or {}
            attr = names.get("#s", "state")
            row[attr] = vals[":s"]
        if ":m" in vals:
            row["messages"] = vals[":m"]
        if ":u" in vals:
            row["updatedAt"] = vals[":u"]
        if ":nr" in vals:
            row["revision"] = vals[":nr"]
        return {}


def _staff(org="org-nus"):
    return Principal(user_id="staff-1", email="staff@x", groups=["Staff"], organisation_id=org)


def _claim(state=cs.STATE_SUBMITTED, org="org-nus", cand="found-1"):
    return {
        "claimId": "claim-1", "claimantId": "u1", "claimantEmail": "u1@x",
        "queryItemId": "lost-1", "candidateItemId": cand, "organisationId": org,
        "state": state, "messages": [],
    }


def _wire(monkeypatch, claims_rows, items_rows=None):
    claims = FakeTable(claims_rows)
    items = FakeTable(items_rows or {})
    monkeypatch.setattr(ch, "_claims", lambda: claims)
    monkeypatch.setattr(ch, "_items", lambda: items)

    def fake_transact_claim_and_item(**kwargs):
        claims.update_item(
            Key={"claimId": kwargs["claim_id"]},
            UpdateExpression="SET #s = :s, messages = :m, updatedAt = :u, revision = :nr",
            ExpressionAttributeNames={"#s": "state"},
            ExpressionAttributeValues={
                ":s": kwargs["new_state"],
                ":m": kwargs["messages"],
                ":u": kwargs["updated_at"],
                ":nr": kwargs["next_revision"],
            },
        )
        items.update_item(
            Key={"itemId": kwargs["candidate_item_id"]},
            UpdateExpression="SET #s = :s, updatedAt = :u",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":s": "reserved" if kwargs["new_state"] == cs.STATE_RESERVED else "closed",
                ":u": kwargs["updated_at"],
            },
        )

    monkeypatch.setattr(ch, "_transact_claim_and_item", fake_transact_claim_and_item)
    # no real SES
    monkeypatch.delenv("SENDER_EMAIL", raising=False)
    return claims, items


def _key(**kw):
    return tuple(sorted(kw.items()))


def test_approve_then_reserve_then_handover(monkeypatch):
    c = _claim()
    claims, items = _wire(monkeypatch, {_key(claimId="claim-1"): c},
                          {_key(itemId="found-1"): {"itemId": "found-1", "status": "available"}})
    p = _staff()

    r = ch._staff_transition(p, "claim-1", "approve", {})
    assert r["statusCode"] == 200
    assert claims.rows[_key(claimId="claim-1")]["state"] == cs.STATE_APPROVED

    r = ch._staff_transition(p, "claim-1", "reserve", {})
    assert claims.rows[_key(claimId="claim-1")]["state"] == cs.STATE_RESERVED
    assert items.rows[_key(itemId="found-1")]["status"] == "reserved"

    r = ch._staff_transition(p, "claim-1", "hand_over", {})
    assert claims.rows[_key(claimId="claim-1")]["state"] == cs.STATE_HANDED_OVER
    assert items.rows[_key(itemId="found-1")]["status"] == "closed"


def test_reject_path(monkeypatch):
    claims, _ = _wire(monkeypatch, {_key(claimId="claim-1"): _claim()},
                      {_key(itemId="found-1"): {"itemId": "found-1", "status": "available"}})
    r = ch._staff_transition(_staff(), "claim-1", "reject", {"message": "not enough proof"})
    assert claims.rows[_key(claimId="claim-1")]["state"] == cs.STATE_REJECTED


def test_invalid_staff_transition_409(monkeypatch):
    _wire(monkeypatch, {_key(claimId="claim-1"): _claim(state=cs.STATE_APPROVED)},
          {_key(itemId="found-1"): {"itemId": "found-1"}})
    r = ch._staff_transition(_staff(), "claim-1", "approve", {})  # already approved
    assert r["statusCode"] == 409


def test_request_info_requires_a_question(monkeypatch):
    _wire(monkeypatch, {_key(claimId="claim-1"): _claim()})
    r = ch._staff_transition(_staff(), "claim-1", "request_info", {"message": "   "})
    assert r["statusCode"] == 400


def test_cross_org_claim_denied(monkeypatch):
    _wire(monkeypatch, {_key(claimId="claim-1"): _claim(org="org-other")})
    with pytest.raises(AuthError) as ei:
        ch._load_org_claim(_staff(org="org-nus"), "claim-1")
    assert ei.value.status == 403


def test_notify_withdrawn_claims_rejects_active_only(monkeypatch):
    active = _claim(state=cs.STATE_SUBMITTED, cand="found-1")
    active["claimId"] = "claim-active"
    terminal = _claim(state=cs.STATE_HANDED_OVER, cand="found-1")
    terminal["claimId"] = "claim-done"
    other_item = _claim(state=cs.STATE_SUBMITTED, cand="found-999")
    other_item["claimId"] = "claim-other"
    rows = {
        _key(claimId="claim-active"): active,
        _key(claimId="claim-done"): terminal,
        _key(claimId="claim-other"): other_item,
    }
    claims, _ = _wire(monkeypatch, rows)
    n = ch.notify_withdrawn_claims("org-nus", "found-1")
    assert n == 1  # only the active claim on found-1
    assert claims.rows[_key(claimId="claim-active")]["state"] == cs.STATE_REJECTED
    assert claims.rows[_key(claimId="claim-done")]["state"] == cs.STATE_HANDED_OVER  # untouched
    assert claims.rows[_key(claimId="claim-other")]["state"] == cs.STATE_SUBMITTED  # untouched
