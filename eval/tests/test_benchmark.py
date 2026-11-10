"""Structural checks on the hand-authored benchmark (no network, no vectors)."""

import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from benchmark import GROUPS, build_benchmark  # noqa: E402
from pipeline.location import in_service_area  # noqa: E402


def test_size_is_100_lost_200_found():
    ds = build_benchmark()
    assert len(ds["lost"]) == 100
    assert len(ds["found"]) == 200


def test_ids_unique_and_every_truth_exists():
    ds = build_benchmark()
    lost_ids = [r["id"] for r in ds["lost"]]
    found_ids = [r["id"] for r in ds["found"]]
    assert len(set(lost_ids)) == len(lost_ids)
    assert len(set(found_ids)) == len(found_ids)
    truths = [r["truth"] for r in ds["lost"] if r["truth"]]
    assert len(truths) == len(GROUPS) == len(set(truths))
    assert set(truths) <= set(found_ids)


def test_every_pair_has_a_same_category_hard_negative():
    ds = build_benchmark()
    negatives = Counter(r["category"] for r in ds["found"] if r["kind"] == "hard_negative")
    pairs = Counter(r["category"] for r in ds["lost"] if r["kind"] == "pair")
    assert negatives == pairs


def test_coordinates_in_service_area_and_no_zones():
    ds = build_benchmark()
    for rec in ds["lost"] + ds["found"]:
        loc = rec["location"]
        assert in_service_area(loc["latitude"], loc["longitude"]), rec["id"]
        assert "locationZone" not in rec


def test_deterministic_for_a_seed():
    assert build_benchmark(1) == build_benchmark(1)
    assert build_benchmark(1) != build_benchmark(2)


def test_pairs_are_not_all_colocated():
    bands = Counter(r["locationBand"] for r in build_benchmark()["lost"] if r["kind"] == "pair")
    assert set(bands) == {"same", "nearby", "far"}


def test_small_is_20_lost_40_found_with_valid_truths():
    for conditions in ("realistic", "best_case"):
        ds = build_benchmark(size="small", conditions=conditions)
        assert (len(ds["lost"]), len(ds["found"])) == (20, 40)
        found_ids = {r["id"] for r in ds["found"]}
        truths = [r["truth"] for r in ds["lost"] if r["truth"]]
        assert len(truths) == 12 and set(truths) <= found_ids


def test_best_case_has_no_lookalikes_and_all_pairs_colocated_within_hours():
    ds = build_benchmark(size="small", conditions="best_case")
    assert not any(r["kind"] == "hard_negative" for r in ds["found"])
    pairs = [r for r in ds["lost"] if r["kind"] == "pair"]
    assert {r["locationBand"] for r in pairs} == {"same"}
    assert {r["delayBand"] for r in pairs} == {"hours"}
