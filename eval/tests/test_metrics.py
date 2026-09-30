"""Unit tests for the pure retrieval + notification metrics."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from metrics import (  # noqa: E402
    RankedQuery, hit_at_1, recall_at_k, mrr, notification_metrics,
)


def test_hit_at_1():
    qs = [
        RankedQuery("a", ["x", "y", "z"], [0.9, 0.5, 0.1], truth="x"),  # hit
        RankedQuery("b", ["y", "x"], [0.8, 0.7], truth="x"),            # miss (x rank 2)
        RankedQuery("c", ["z"], [0.6], truth=None),                     # ignored (no truth)
    ]
    assert hit_at_1(qs) == 0.5  # 1 of 2 evaluable


def test_recall_at_k():
    qs = [
        RankedQuery("a", ["x", "y", "z", "w", "v", "u"], [0.9]*6, truth="v"),  # rank 5 -> in top5
        RankedQuery("b", ["y", "x", "z", "w", "v", "u"], [0.9]*6, truth="u"),  # rank 6 -> not in top5
    ]
    assert recall_at_k(qs, 5) == 0.5


def test_mrr():
    qs = [
        RankedQuery("a", ["x", "y"], [0.9, 0.1], truth="x"),  # 1/1
        RankedQuery("b", ["y", "x"], [0.9, 0.1], truth="x"),  # 1/2
    ]
    assert mrr(qs) == (1.0 + 0.5) / 2


def test_notification_metrics_precision_and_missed():
    qs = [
        # true match x scores above threshold (correct alert), y below
        RankedQuery("a", ["x", "y"], [0.9, 0.4], truth="x"),
        # true match z below threshold -> missed; w above -> incorrect alert
        RankedQuery("b", ["w", "z"], [0.85, 0.5], truth="z"),
    ]
    nm = notification_metrics(qs, threshold=0.7)
    assert nm.alerts_total == 2         # x (0.9) and w (0.85)
    assert nm.alert_precision == 0.5    # 1 correct of 2
    assert nm.missed_notification_rate == 0.5  # b's true match missed
    assert nm.false_alert_rate == 0.0   # no truth=None queries here


def test_notification_false_alert_rate_on_no_truth_queries():
    qs = [
        RankedQuery("a", ["x"], [0.9], truth=None),  # fires an alert but there's no true match
        RankedQuery("b", ["y"], [0.4], truth=None),  # no alert
    ]
    nm = notification_metrics(qs, threshold=0.7)
    assert nm.false_alert_rate == 0.5
    assert nm.alert_precision == 0.0  # all alerts incorrect
