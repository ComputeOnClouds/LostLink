"""Evaluation harness: rank found items for each lost item using the PURE scorer.

Imports BlendedScorer from backend/pipeline (no AWS needed — proven pure in Task 9) and
ranks candidates under a given weight map, then computes metrics across variants.

Ground-truth format (JSON):
{
  "lost":  [{"id","description","locationZone","eventTime","truth": <found id or null>,
             "vecText": [...]}],
  "found": [{"id","description","locationZone","eventTime","vecText": [...]}]
}
Vectors are optional in the file; if absent, embed_dataset() fills them via Bedrock.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass

# Import the pure scoring pieces from the backend package.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from pipeline.models import Item, ItemType, VectorMap  # noqa: E402
from pipeline.impl.scorer import BlendedScorer  # noqa: E402
from pipeline.location import location_from_dict, within_search_radius  # noqa: E402

from metrics import RankedQuery, hit_at_1, recall_at_k, mrr, notification_metrics  # noqa: E402

_scorer = BlendedScorer(float(os.environ.get("LOCATION_HALF_DISTANCE_METRES", "500")))

# Weight variants compared in the evaluation (RATIONALE ADR-004). Image variants are
# reserved for when Option 2 is enabled.
VARIANTS: dict[str, dict[str, float]] = {
    "text_only": {"text": 1.0, "location": 0.0, "time": 0.0},
    "text_location": {"text": 0.7, "location": 0.3, "time": 0.0},
    "text_location_time": {"text": 0.6, "location": 0.25, "time": 0.15},
}


def _to_item(rec: dict, item_type: ItemType) -> Item:
    return Item(
        item_id=rec["id"],
        item_type=item_type,
        organisation_id=rec.get("organisationId", "eval-org"),
        owner_id="eval",
        description=rec.get("description"),
        location_zone=rec.get("locationZone"),
        location=location_from_dict(rec.get("location")),
        search_radius_metres=rec.get("searchRadiusMetres"),
        event_time=rec.get("eventTime"),
        vectors=VectorMap(text=rec.get("vecText")),
    )


def rank_variant(dataset: dict, weights: dict[str, float]) -> list[RankedQuery]:
    """For each lost item, score against all found items and rank, under ``weights``."""
    found_items = [_to_item(f, ItemType.FOUND) for f in dataset["found"]]
    results: list[RankedQuery] = []
    for lost_rec in dataset["lost"]:
        lost = _to_item(lost_rec, ItemType.LOST)
        scored = []
        for f in found_items:
            if not within_search_radius(lost, f):
                continue
            r = _scorer.score(lost, f, weights)
            scored.append((f.item_id, r.score))
        scored.sort(key=lambda t: t[1], reverse=True)
        results.append(RankedQuery(
            query_id=lost.item_id,
            ranked=[cid for cid, _ in scored],
            scores=[s for _, s in scored],
            truth=lost_rec.get("truth"),
        ))
    return results


@dataclass
class VariantReport:
    variant: str
    hit_at_1: float
    recall_at_5: float
    mrr: float
    alert_precision: float
    false_alert_rate: float
    missed_notification_rate: float


def evaluate(dataset: dict, threshold: float = 0.7) -> list[VariantReport]:
    reports = []
    for name, weights in VARIANTS.items():
        queries = rank_variant(dataset, weights)
        nm = notification_metrics(queries, threshold)
        reports.append(VariantReport(
            variant=name,
            hit_at_1=round(hit_at_1(queries), 4),
            recall_at_5=round(recall_at_k(queries, 5), 4),
            mrr=round(mrr(queries), 4),
            alert_precision=round(nm.alert_precision, 4),
            false_alert_rate=round(nm.false_alert_rate, 4),
            missed_notification_rate=round(nm.missed_notification_rate, 4),
        ))
    return reports


def load_dataset(path: str) -> dict:
    with open(path) as f:
        return json.load(f)
