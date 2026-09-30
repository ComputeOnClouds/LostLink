"""Notifier implementation — Amazon SES with per-report-item-pair dedup (Task 10).

Delivery channel is hidden behind the Notifier interface (SES today). Deduplication uses
a DynamoDB conditional update on the Matches row: the notifier atomically flips
``notified`` from false->true and only sends the email if it won that update. This makes
notification exactly-once per report-item pair even when the SQS worker reprocesses a
message (redelivery, DLQ retry, or a found item and a lost report both triggering the
same pair).

Config (env):
    MATCHES_TABLE  - Matches table name (for the dedup flag)
    SENDER_EMAIL   - verified SES sender identity
    BEDROCK_REGION / AWS_REGION - region for the SES client
    CLOUDFRONT_URL - optional, linked in the email so the user can view the suggestion
"""

from __future__ import annotations

import os

from ..interfaces import Notifier
from ..models import MatchResult


class SesNotifier(Notifier):
    def __init__(self, ses_client=None, dynamodb_resource=None) -> None:
        self._region = os.environ.get("BEDROCK_REGION") or os.environ.get(
            "AWS_REGION", "ap-southeast-2"
        )
        self._matches_table_name = os.environ.get("MATCHES_TABLE")
        self._sender = os.environ.get("SENDER_EMAIL")
        self._app_url = os.environ.get("CLOUDFRONT_URL", "")
        self._ses = ses_client
        self._ddb = dynamodb_resource

    @property
    def ses(self):
        if self._ses is None:
            import boto3

            self._ses = boto3.client("ses", region_name=self._region)
        return self._ses

    @property
    def _matches(self):
        if self._ddb is None:
            import boto3

            self._ddb = boto3.resource("dynamodb", region_name=self._region)
        if not self._matches_table_name:
            raise RuntimeError("MATCHES_TABLE env var is not set")
        return self._ddb.Table(self._matches_table_name)

    def notify(self, recipient: str, match: MatchResult) -> None:
        # If we can't actually send (no verified sender configured, or a non-email
        # recipient), do nothing — and do NOT consume the dedup claim, so the email can
        # still go out later once a real sender is verified. This keeps notification
        # entirely decoupled from the match-persistence path.
        if not self._can_send(recipient):
            print(
                f"[notify] send not possible (sender={self._sender!r}); "
                f"recording match without emailing {recipient!r}"
            )
            return

        # Claim the pair atomically; only the winner sends (exactly-once).
        if not self._claim(match):
            print(
                f"[notify] already notified for {match.query_item_id}->"
                f"{match.candidate_item_id}; skipping"
            )
            return

        subject = "LostLink: a potential match for your lost item"
        body = (
            "Good news — a partner organisation may be holding an item that matches your "
            "report.\n\n"
            "For your privacy and to verify ownership, the item's details stay hidden "
            "until you submit a claim and the organisation confirms it is yours.\n\n"
            + (f"View the suggestion and start a claim: {self._app_url}\n\n" if self._app_url else "")
            + "— LostLink"
        )
        # Best-effort: a send failure (e.g. SES sandbox rejects an unverified recipient)
        # must never break the matching pipeline. Log and move on.
        try:
            self.ses.send_email(
                Source=self._sender,
                Destination={"ToAddresses": [recipient]},
                Message={
                    "Subject": {"Data": subject},
                    "Body": {"Text": {"Data": body}},
                },
            )
            print(f"[notify] emailed {recipient} for {match.query_item_id}->{match.candidate_item_id}")
        except Exception as e:  # noqa: BLE001
            print(f"[notify] SES send failed (non-fatal): {e!r}")

    def _can_send(self, recipient: str) -> bool:
        """True only if a real verified-capable sender and a plausible recipient exist."""
        if not self._sender or self._sender.endswith(".example"):
            return False
        if not recipient or "@" not in recipient:
            return False
        return True

    def _claim(self, match: MatchResult) -> bool:
        """Atomically set notified=true only if it is currently false/absent.

        Returns True if this call won the claim (i.e. should send), False otherwise.
        """
        try:
            self._matches.update_item(
                Key={
                    "queryItemId": match.query_item_id,
                    "candidateItemId": match.candidate_item_id,
                },
                UpdateExpression="SET notified = :t",
                ConditionExpression="attribute_not_exists(notified) OR notified = :f",
                ExpressionAttributeValues={":t": True, ":f": False},
            )
            return True
        except Exception as e:  # noqa: BLE001 — ConditionalCheckFailed means already notified
            if "ConditionalCheckFailed" in type(e).__name__ or "ConditionalCheckFailed" in str(e):
                return False
            # Any other error: don't silently drop; re-raise so the message can retry.
            raise
