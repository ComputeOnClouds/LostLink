"""Sanity test: run the harness on the committed sample dataset (no Bedrock).

Confirms the pure scorer + metrics produce sensible numbers on a tiny hand-labelled set
where each lost item's true found item is clearly the closest.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from harness import evaluate, load_dataset, rank_variant, VARIANTS  # noqa: E402


SAMPLE = os.path.join(os.path.dirname(__file__), "..", "data", "sample_dataset.json")


def test_sample_dataset_perfect_top1_on_full_variant():
    ds = load_dataset(SAMPLE)
    reports = {r.variant: r for r in evaluate(ds, threshold=0.7)}
    full = reports["text_location_time"]
    # Each of the 3 true pairs is the closest by text + same zone + near time.
    assert full.hit_at_1 == 1.0
    assert full.recall_at_5 == 1.0
    assert full.mrr == 1.0


def test_rank_puts_true_match_first():
    ds = load_dataset(SAMPLE)
    qs = rank_variant(ds, VARIANTS["text_location_time"])
    by_id = {q.query_id: q for q in qs}
    assert by_id["l-wallet"].ranked[0] == "f-wallet"
    assert by_id["l-bottle"].ranked[0] == "f-bottle"
    assert by_id["l-umbrella"].ranked[0] == "f-umbrella"


def test_all_variants_present():
    ds = load_dataset(SAMPLE)
    reports = evaluate(ds, threshold=0.7)
    assert {r.variant for r in reports} == set(VARIANTS.keys())
