"""Retrieval + notification metrics for the LostLink matching evaluation.

Pure functions (no AWS). Given, for each lost item, a ranked list of candidate found
items and the ground-truth correct found item, compute standard retrieval metrics and
notification metrics at a threshold.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RankedQuery:
    """One lost item's evaluation result.

    ranked: candidate found-item ids, best first.
    scores: parallel list of scores for those candidates (same order as ranked).
    truth: the id of the correct found item (or None if the item has no true match).
    """

    query_id: str
    ranked: list[str]
    scores: list[float]
    truth: str | None


def hit_at_1(queries: list[RankedQuery]) -> float:
    """Fraction of queries whose top-ranked candidate is the true match.

    Only queries that actually have a true match (truth != None) are counted.
    """
    evaluable = [q for q in queries if q.truth is not None]
    if not evaluable:
        return 0.0
    hits = sum(1 for q in evaluable if q.ranked and q.ranked[0] == q.truth)
    return hits / len(evaluable)


def recall_at_k(queries: list[RankedQuery], k: int) -> float:
    """Fraction of queries whose true match appears anywhere in the top-k results."""
    evaluable = [q for q in queries if q.truth is not None]
    if not evaluable:
        return 0.0
    hits = sum(1 for q in evaluable if q.truth in q.ranked[:k])
    return hits / len(evaluable)


def mrr(queries: list[RankedQuery]) -> float:
    """Mean Reciprocal Rank over queries that have a true match."""
    evaluable = [q for q in queries if q.truth is not None]
    if not evaluable:
        return 0.0
    total = 0.0
    for q in evaluable:
        if q.truth in q.ranked:
            rank = q.ranked.index(q.truth) + 1
            total += 1.0 / rank
    return total / len(evaluable)


@dataclass
class NotificationMetrics:
    alert_precision: float          # of alerts fired, fraction that were the true match
    false_alert_rate: float         # of no-true-match queries, fraction that fired an alert
    missed_notification_rate: float # of true-match queries, fraction with no correct alert
    alert_burden: float             # mean incorrect alerts per query
    alerts_total: int


def notification_metrics(queries: list[RankedQuery], threshold: float) -> NotificationMetrics:
    """An "alert" fires for every candidate scoring >= threshold.

    - alert_precision: correct alerts / total alerts.
    - false_alert_rate: over queries WITHOUT a true match, fraction that fired >=1 alert.
    - missed_notification_rate: over queries WITH a true match, fraction where the true
      match did NOT score >= threshold (so no correct alert).
    - alert_burden: mean number of incorrect alerts per query.
    """
    alerts_total = 0
    correct_alerts = 0
    incorrect_alerts = 0

    with_truth = [q for q in queries if q.truth is not None]
    without_truth = [q for q in queries if q.truth is None]

    missed = 0
    for q in with_truth:
        fired_correct = False
        for cand, score in zip(q.ranked, q.scores):
            if score >= threshold:
                alerts_total += 1
                if cand == q.truth:
                    correct_alerts += 1
                    fired_correct = True
                else:
                    incorrect_alerts += 1
        if not fired_correct:
            missed += 1

    false_alert_queries = 0
    for q in without_truth:
        fired = False
        for score in q.scores:
            if score >= threshold:
                alerts_total += 1
                incorrect_alerts += 1
                fired = True
        if fired:
            false_alert_queries += 1

    n_queries = len(queries) or 1
    return NotificationMetrics(
        alert_precision=(correct_alerts / alerts_total) if alerts_total else 0.0,
        false_alert_rate=(false_alert_queries / len(without_truth)) if without_truth else 0.0,
        missed_notification_rate=(missed / len(with_truth)) if with_truth else 0.0,
        alert_burden=incorrect_alerts / n_queries,
        alerts_total=alerts_total,
    )
