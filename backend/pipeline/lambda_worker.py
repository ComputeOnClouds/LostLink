"""Lambda entry point for the SQS-triggered matching worker.

Unwraps SQS records (each body is a match job {"itemId","type"}) and runs the
MatchWorker for each. Uses partial-batch-response so a single bad record is retried /
DLQ'd without reprocessing the whole batch.
"""

from __future__ import annotations

import json

from .worker import MatchWorker

_worker = None


def _get_worker() -> MatchWorker:
    global _worker
    if _worker is None:
        _worker = MatchWorker.from_env()
    return _worker


def handler(event, _context=None):
    worker = _get_worker()
    failures = []
    for record in event.get("Records", []):
        message_id = record.get("messageId")
        try:
            job = json.loads(record["body"])
            worker.handle(job)
        except Exception as e:  # noqa: BLE001
            print(f"failed to process message {message_id}: {e!r}")
            failures.append({"itemIdentifier": message_id})
    return {"batchItemFailures": failures}
