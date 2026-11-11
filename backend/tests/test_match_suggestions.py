import json
from types import SimpleNamespace

import pytest
import boto3
from boto3.dynamodb.conditions import Key
from botocore.awsrequest import AWSResponse
from botocore.exceptions import ClientError

from api import claims_handler
from api.auth import Principal


def test_match_suggestions_exclude_claimed_pairs_across_all_states(monkeypatch):
    principal = Principal("owner-1", None, ["Individual"], None)
    states = ["submitted", "info_requested", "approved", "rejected", "reserved", "handed_over", "cancelled"]
    claims = [
        {"queryItemId": "lost-1", "candidateItemId": f"found-{state}", "state": state}
        for state in states
    ]
    cursor = {"claimId": "claim-4", "claimantId": principal.user_id}
    claim_pages = []

    def query_claims(**kwargs):
        assert kwargs["IndexName"] == "by-owner"
        assert kwargs["KeyConditionExpression"] == Key("claimantId").eq(principal.user_id)
        claim_pages.append(kwargs.get("ExclusiveStartKey"))
        if kwargs.get("ExclusiveStartKey") == cursor:
            return {"Items": claims[4:]}
        return {"Items": claims[:4], "LastEvaluatedKey": cursor}

    def suggestion(report_id, found_id):
        return {"queryItemId": report_id, "candidateItemId": found_id, "organisationId": "org-1", "score": 0.8}

    rows = {
        "lost-1": [suggestion("lost-1", claim["candidateItemId"]) for claim in claims]
        + [suggestion("lost-1", "found-new"), {
            **suggestion("lost-1", "found-marked"), "submittedClaimId": "new-claim",
        }],
        "lost-2": [suggestion("lost-2", "found-rejected")],
    }

    def query_matches(KeyConditionExpression, ConsistentRead):
        assert ConsistentRead is True
        return {"Items": rows[KeyConditionExpression.get_expression()["values"][1]]}

    items = SimpleNamespace(
        query=lambda **kwargs: {"Items": [{"itemId": report_id, "itemType": "lost"} for report_id in rows]},
        get_item=lambda **kwargs: {"Item": {"status": "available", "description": "private description"}},
    )
    monkeypatch.setattr(claims_handler, "_items", lambda: items)
    monkeypatch.setattr(claims_handler, "_claims", lambda: SimpleNamespace(query=query_claims))
    monkeypatch.setattr(claims_handler, "_matches", lambda: SimpleNamespace(query=query_matches))

    response = claims_handler._list_matches(principal)

    assert response["statusCode"] == 200
    assert claim_pages == [None, cursor]
    assert "private description" not in response["body"]
    assert {
        (match["queryItemId"], match["candidateItemId"])
        for match in json.loads(response["body"])["matches"]
    } == {("lost-1", "found-new"), ("lost-2", "found-rejected")}


def _wire_submission(monkeypatch, *, history=(), marker=None):
    principal = Principal("owner-1", "owner@example.com", ["Individual"], None)
    report = {"ownerId": principal.user_id, "itemType": "lost", "status": "matched"}
    match = {"organisationId": "org-1", "active": True}
    if marker:
        match["submittedClaimId"] = marker
    monkeypatch.setattr(claims_handler, "_items", lambda: SimpleNamespace(get_item=lambda **kwargs: {"Item": report}))
    monkeypatch.setattr(claims_handler, "_matches", lambda: SimpleNamespace(get_item=lambda **kwargs: {"Item": match}))
    monkeypatch.setattr(claims_handler, "_own_claims", lambda _: iter(history))
    monkeypatch.setattr(claims_handler, "_MATCHES_TABLE", "Matches")
    monkeypatch.setattr(claims_handler, "_CLAIMS_TABLE", "Claims")
    return principal, {"queryItemId": "lost-1", "candidateItemId": "found-1", "evidenceText": "Red stripe inside"}


@pytest.mark.parametrize("state", ["submitted", "info_requested", "approved", "rejected", "reserved", "handed_over", "cancelled"])
def test_legacy_claim_blocks_repeat_submission_in_every_state(monkeypatch, state):
    principal, body = _wire_submission(monkeypatch, history=[{
        "queryItemId": "lost-1", "candidateItemId": "found-1", "state": state,
    }])

    response = claims_handler._create_claim(principal, body)

    assert response["statusCode"] == 409
    assert "My claims" in response["body"]


def test_match_marker_blocks_submission_before_claim_index_catches_up(monkeypatch):
    principal, body = _wire_submission(monkeypatch, marker="existing-claim")

    assert claims_handler._create_claim(principal, body)["statusCode"] == 409


def test_stale_prechecks_cannot_create_two_claims_for_the_same_pair(monkeypatch):
    principal, body = _wire_submission(monkeypatch)
    transactions = []
    created_claims = []

    def transact_write_items(*, TransactItems):
        update = TransactItems[0]["Update"]
        put = TransactItems[1]["Put"]
        assert update["TableName"] == "Matches"
        assert update["Key"] == {"queryItemId": "lost-1", "candidateItemId": "found-1"}
        assert "attribute_not_exists(submittedClaimId)" in update["ConditionExpression"]
        assert update["ExpressionAttributeValues"][":claim"] == put["Item"]["claimId"]
        assert put["TableName"] == "Claims"
        transactions.append(TransactItems)
        if created_claims:
            raise ClientError({
                "Error": {"Code": "TransactionCanceledException", "Message": "Already claimed"},
                "CancellationReasons": [{"Code": "ConditionalCheckFailed"}, {"Code": "None"}],
            }, "TransactWriteItems")
        created_claims.append(put["Item"])

    client = SimpleNamespace(transact_write_items=transact_write_items)
    monkeypatch.setattr(claims_handler, "_ddb", SimpleNamespace(meta=SimpleNamespace(client=client)))

    # Both prechecks see the same stale, unclaimed match and empty claim history.
    assert claims_handler._create_claim(principal, body)["statusCode"] == 201
    assert claims_handler._create_claim(principal, body)["statusCode"] == 409
    assert len(transactions) == 2
    assert len(created_claims) == 1


def _capture_transaction_requests(monkeypatch):
    resource = boto3.resource(
        "dynamodb", region_name="ap-southeast-1", aws_access_key_id="test", aws_secret_access_key="test",
    )
    requests = []

    def capture(request, **kwargs):
        requests.append(json.loads(request.body))
        # Exercise the real SDK serialization, then intercept before any network I/O.
        return AWSResponse(request.url, 200, {}, SimpleNamespace(stream=lambda: iter([b"{}"])))

    resource.meta.client.meta.events.register("before-send.dynamodb.TransactWriteItems", capture)
    monkeypatch.setattr(claims_handler, "_ddb", resource)
    return requests


def test_claim_creation_serializes_once_with_the_real_resource_client(monkeypatch):
    principal, body = _wire_submission(monkeypatch)
    requests = _capture_transaction_requests(monkeypatch)

    response = claims_handler._create_claim(principal, body)

    assert response["statusCode"] == 201
    update, put = requests[0]["TransactItems"]
    assert update["Update"]["Key"] == {"queryItemId": {"S": "lost-1"}, "candidateItemId": {"S": "found-1"}}
    assert put["Put"]["Item"]["claimId"] == {"S": json.loads(response["body"])["claimId"]}
    assert put["Put"]["Item"]["revision"] == {"N": "1"}
    assert update["Update"]["ExpressionAttributeValues"][":active"] == {"BOOL": True}


@pytest.mark.parametrize("state, item_status", [("reserved", "reserved"), ("handed_over", "closed")])
def test_collection_transaction_serializes_once_with_the_real_resource_client(monkeypatch, state, item_status):
    monkeypatch.setattr(claims_handler, "_CLAIMS_TABLE", "Claims")
    monkeypatch.setattr(claims_handler, "_ITEMS_TABLE", "Items")
    requests = _capture_transaction_requests(monkeypatch)

    claims_handler._transact_claim_and_item(
        claim_id="claim-1", candidate_item_id="found-1", expected_state="approved", new_state=state,
        messages=[], expected_revision=1, next_revision=2, updated_at="2026-11-08T00:00:00Z",
    )

    claim_update, item_update = [item["Update"] for item in requests[0]["TransactItems"]]
    assert claim_update["Key"] == {"claimId": {"S": "claim-1"}}
    assert claim_update["ExpressionAttributeValues"][":nr"] == {"N": "2"}
    assert item_update["Key"] == {"itemId": {"S": "found-1"}}
    assert item_update["ExpressionAttributeValues"][":status"] == {"S": item_status}
