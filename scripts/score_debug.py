#!/usr/bin/env python3
"""Score every current lost report against every current found item and print the
per-component breakdown, so we can see exactly why a pair is above/below threshold.

Uses the real BlendedScorer, so the numbers match what the matching worker computes.
"""
import os
import sys

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from pipeline.impl.ddb_mapping import ddb_to_item  # noqa: E402
from pipeline.impl.scorer import BlendedScorer  # noqa: E402
from pipeline.models import ItemType  # noqa: E402

REGION = os.environ.get("AWS_REGION", "ap-southeast-2")
ITEMS = os.environ["ITEMS_TABLE"]
THRESH = float(os.environ.get("MATCH_THRESHOLD", "0.7"))
WEIGHTS = {
    "text": float(os.environ.get("WEIGHT_TEXT", "0.6")),
    "image": float(os.environ.get("WEIGHT_IMAGE", "0.0")),
    "location": float(os.environ.get("WEIGHT_LOCATION", "0.25")),
    "time": float(os.environ.get("WEIGHT_TIME", "0.15")),
}


def g(breakdown, name):
    v = breakdown.get(name)
    return f"{v:.3f}" if isinstance(v, (int, float)) else "  -  "


ddb = boto3.resource("dynamodb", region_name=REGION)
rows = ddb.Table(ITEMS).scan().get("Items", [])
items = [ddb_to_item(r) for r in rows]
lost = [i for i in items if i.item_type is ItemType.LOST]
found = [i for i in items if i.item_type is ItemType.FOUND]
scorer = BlendedScorer()

print(f"weights={WEIGHTS}  threshold={THRESH}")
print(f"{len(lost)} lost / {len(found)} found items\n")
for L in lost:
    has_vec = "y" if L.vectors.text else "NO-VEC"
    print(f"LOST {L.item_id[:14]} desc={L.description!r} zone={L.location_zone!r} "
          f"time={L.event_time} text-vec={has_vec}")
    for F in found:
        r = scorer.score(L, F, WEIGHTS)
        b = r.breakdown
        verdict = "MATCH" if r.score >= THRESH else "below"
        print(f"   vs FOUND {F.item_id[:14]} desc={F.description!r} zone={F.location_zone!r}")
        print(f"      text={g(b,'text')} location={g(b,'location')} time={g(b,'time')} "
              f"-> blended={r.score:.4f}  [{verdict}]  (components present: {sorted(b)})")
    print()
