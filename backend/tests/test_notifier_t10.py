"""Task 10 unit tests for SesNotifier: per-report-item-pair dedup + send construction.

Uses fakes for DynamoDB (conditional update) and SES to prove exactly-once delivery and
correct email construction, without AWS.
"""

import os

import pytest

from pipeline.models import MatchResult
from pipeline.impl.notifier import SesNotifier


class ConditionalCheckFailedException(Exception):
    """Mimics botocore's ConditionalCheckFailedException by class name."""


class FakeTable:
    """Emulates a Matches row with a 'notified' flag under conditional update."""

    def __init__(self, notified=False):
        self.notified = notified
        self.update_calls = 0

    def update_item(self, Key=None, UpdateExpression=None, ConditionExpression=None,
                    ExpressionAttributeValues=None):
        self.update_calls += 1
        # Condition: notified absent OR notified == false.
        if self.notified is True:
            raise ConditionalCheckFailedException("ConditionalCheckFailed")
        self.notified = True
        return {}


class FakeDDB:
    def __init__(self, table):
        self._table = table

    def Table(self, name):
        return self._table


class FakeSES:
    def __init__(self):
        self.sent = []

    def send_email(self, Source=None, Destination=None, Message=None):
        self.sent.append({"Source": Source, "Destination": Destination, "Message": Message})
        return {"MessageId": "fake"}


def _match():
    return MatchResult(
        query_item_id="lost-1", candidate_item_id="found-1", organisation_id="org-nus",
        score=0.9, profile_name="text_location_time", breakdown={},
    )


def _notifier(table, ses, monkeypatch, sender="no-reply@lostlink.test"):
    monkeypatch.setenv("MATCHES_TABLE", "LostLink-Matches")
    monkeypatch.setenv("SENDER_EMAIL", sender)
    return SesNotifier(ses_client=ses, dynamodb_resource=FakeDDB(table))


def test_first_notify_sends_and_claims(monkeypatch):
    table = FakeTable(notified=False)
    ses = FakeSES()
    n = _notifier(table, ses, monkeypatch)
    n.notify("user@simulator.amazonses.com", _match())
    assert table.notified is True
    assert len(ses.sent) == 1
    assert ses.sent[0]["Destination"]["ToAddresses"] == ["user@simulator.amazonses.com"]
    assert ses.sent[0]["Source"] == "no-reply@lostlink.test"


def test_second_notify_is_deduped(monkeypatch):
    table = FakeTable(notified=False)
    ses = FakeSES()
    n = _notifier(table, ses, monkeypatch)
    m = _match()
    n.notify("user@simulator.amazonses.com", m)
    n.notify("user@simulator.amazonses.com", m)  # reprocessing
    assert len(ses.sent) == 1  # exactly once
    assert table.update_calls == 2  # both attempted the claim; only one won


def test_no_send_when_sender_unset(monkeypatch):
    table = FakeTable(notified=False)
    ses = FakeSES()
    monkeypatch.setenv("MATCHES_TABLE", "LostLink-Matches")
    monkeypatch.delenv("SENDER_EMAIL", raising=False)
    n = SesNotifier(ses_client=ses, dynamodb_resource=FakeDDB(table))
    n.notify("user@simulator.amazonses.com", _match())
    # no verified sender -> no send AND no claim consumed (so it can send later).
    assert table.notified is False
    assert table.update_calls == 0
    assert ses.sent == []


def test_no_send_when_sender_is_placeholder(monkeypatch):
    table = FakeTable(notified=False)
    ses = FakeSES()
    n = _notifier(table, ses, monkeypatch, sender="no-reply@lostlink.example")
    n.notify("user@simulator.amazonses.com", _match())
    # placeholder ".example" sender is treated as not-sendable; no send, no claim.
    assert ses.sent == []
    assert table.notified is False
    assert table.update_calls == 0


def test_no_send_when_recipient_not_email(monkeypatch):
    table = FakeTable(notified=False)
    ses = FakeSES()
    n = _notifier(table, ses, monkeypatch)
    n.notify("a-cognito-sub-not-an-email", _match())
    assert ses.sent == []  # skipped; recipient isn't an email
    assert table.update_calls == 0  # no claim consumed


def test_ses_send_failure_is_non_fatal(monkeypatch):
    # A rejected send (e.g. SES sandbox) must NOT raise — the match pipeline continues.
    table = FakeTable(notified=False)

    class RejectingSES:
        def send_email(self, **kw):
            raise RuntimeError("MessageRejected: not verified")

    n = _notifier(table, RejectingSES(), monkeypatch)
    n.notify("user@simulator.amazonses.com", _match())  # must not raise
    assert table.notified is True  # claim was made before the (failed) send


def test_email_body_hides_item_details(monkeypatch):
    table = FakeTable(notified=False)
    ses = FakeSES()
    monkeypatch.setenv("CLOUDFRONT_URL", "https://app.example")
    n = _notifier(table, ses, monkeypatch)
    n.notify("user@simulator.amazonses.com", _match())
    body = ses.sent[0]["Message"]["Body"]["Text"]["Data"]
    # privacy: the email must not leak the found item's description/id
    assert "found-1" not in body
    assert "hidden" in body.lower()
    assert "https://app.example" in body
