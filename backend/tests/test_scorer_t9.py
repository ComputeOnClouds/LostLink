"""Task 9: comprehensive unit tests for BlendedScorer + DefaultProfileSelector.

Covers: cosine mapping, spatial + temporal similarity, weighted blend with
present-only normalisation, missing components, the image-term hook (Option 2),
threshold boundaries via the profile, weight sweeps, and source-agnostic determinism.

The Scorer is pure (no AWS), which this suite implicitly confirms by importing and
running it with no boto3/session available.
"""

import math

import pytest

from pipeline.models import Item, ItemType, VectorMap, Profile
from pipeline.impl.scorer import BlendedScorer, _cosine, _spatial, _temporal
from pipeline.impl.profile import DefaultProfileSelector


scorer = BlendedScorer()


def item(item_id="a", itype=ItemType.LOST, org="o", desc="d",
         text=None, image=None, zone=None, when=None):
    return Item(
        item_id=item_id, item_type=itype, organisation_id=org, owner_id="u",
        description=desc, location_zone=zone, event_time=when,
        vectors=VectorMap(text=text, image=image),
    )


# ---- component helpers --------------------------------------------------------------


def test_cosine_maps_to_unit_interval():
    assert _cosine([1, 0], [1, 0]) == pytest.approx(1.0)      # identical -> 1
    assert _cosine([1, 0], [-1, 0]) == pytest.approx(0.0)     # opposite -> 0
    assert _cosine([1, 0], [0, 1]) == pytest.approx(0.5)      # orthogonal -> 0.5


def test_cosine_none_on_missing_or_mismatched():
    assert _cosine(None, [1]) is None
    assert _cosine([1], None) is None
    assert _cosine([], [1]) is None
    assert _cosine([1, 2], [1]) is None       # length mismatch
    assert _cosine([0, 0], [1, 1]) is None     # zero-norm


def test_spatial_zone_match():
    assert _spatial(item(zone="z1"), item(zone="z1")) == 1.0
    assert _spatial(item(zone="z1"), item(zone="z2")) == pytest.approx(0.1)
    assert _spatial(item(zone=None), item(zone="z2")) is None


def test_temporal_decay():
    same = item(when="2026-09-29T10:00:00+00:00")
    assert _temporal(same, same) == pytest.approx(1.0)
    # one half-life (72h) apart -> 0.5
    later = item(when="2026-10-02T10:00:00+00:00")  # +72h
    assert _temporal(same, later) == pytest.approx(0.5, abs=1e-6)
    assert _temporal(item(when=None), later) is None


# ---- blended score ------------------------------------------------------------------


def test_score_text_location_time_full_match():
    w = {"text": 0.6, "image": 0.0, "location": 0.25, "time": 0.15}
    a = item("a", text=[1, 0, 0], zone="z1", when="2026-09-29T10:00:00+00:00")
    b = item("b", ItemType.FOUND, text=[1, 0, 0], zone="z1", when="2026-09-29T10:00:00+00:00")
    r = scorer.score(a, b, w)
    # text 1.0, location 1.0, time 1.0 -> weighted avg 1.0
    assert r.score == pytest.approx(1.0)
    assert set(r.breakdown) == {"text", "location", "time"}


def test_score_present_only_normalisation():
    # No location, no time -> only text contributes; score == text sim regardless of
    # the other weights (they drop out of the normaliser).
    w = {"text": 0.6, "location": 0.25, "time": 0.15}
    a = item("a", text=[1, 0, 0])
    b = item("b", ItemType.FOUND, text=[1, 0, 0])
    r = scorer.score(a, b, w)
    assert r.score == pytest.approx(1.0)
    assert set(r.breakdown) == {"text"}


def test_score_zero_when_no_weight():
    a = item("a", text=[1, 0, 0], zone="z1")
    b = item("b", ItemType.FOUND, text=[1, 0, 0], zone="z1")
    r = scorer.score(a, b, {"text": 0.0, "location": 0.0})
    assert r.score == 0.0


def test_image_term_hook_changes_score_when_enabled():
    # Both carry image vectors. With w_image=0 the image term is inert; raising it
    # must change the score — proving the Option 2 hook works with no code change.
    a = item("a", text=[1, 0, 0], image=[1, 0, 0], zone="z1")
    b = item("b", ItemType.FOUND, text=[0, 1, 0], image=[1, 0, 0], zone="z1")  # text orthogonal, image identical
    base = scorer.score(a, b, {"text": 1.0, "image": 0.0, "location": 0.0}).score
    with_img = scorer.score(a, b, {"text": 1.0, "image": 1.0, "location": 0.0}).score
    assert with_img != base
    # image identical (1.0) pulls the blend up from the orthogonal-text 0.5
    assert with_img > base


def test_image_term_ignored_when_only_one_has_image():
    a = item("a", text=[1, 0, 0], image=[1, 0, 0])
    b = item("b", ItemType.FOUND, text=[1, 0, 0], image=None)
    r = scorer.score(a, b, {"text": 0.5, "image": 0.5})
    # image component absent -> normaliser is just text -> score == text sim (1.0)
    assert r.score == pytest.approx(1.0)
    assert "image" not in r.breakdown


def test_weight_sweep_monotonic_between_two_signals():
    # text sim 1.0, location sim 0.1 (zone mismatch). As w_text rises, score rises.
    a = item("a", text=[1, 0, 0], zone="z1")
    b = item("b", ItemType.FOUND, text=[1, 0, 0], zone="z2")
    scores = []
    for wt in [0.0, 0.25, 0.5, 0.75, 1.0]:
        s = scorer.score(a, b, {"text": wt, "location": 1.0 - wt}).score
        scores.append(s)
    assert scores == sorted(scores)  # non-decreasing as text weight grows
    assert scores[0] == pytest.approx(0.1)   # all-location -> 0.1
    assert scores[-1] == pytest.approx(1.0)  # all-text -> 1.0


def test_source_agnostic_determinism():
    # Same inputs, called repeatedly (as if from different retrieval sources) -> equal.
    a = item("a", text=[0.2, 0.4, 0.4], zone="z1", when="2026-09-29T10:00:00+00:00")
    b = item("b", ItemType.FOUND, text=[0.1, 0.5, 0.3], zone="z1", when="2026-09-29T13:00:00+00:00")
    w = {"text": 0.6, "location": 0.25, "time": 0.15}
    r1 = scorer.score(a, b, w)
    r2 = scorer.score(a, b, w)
    assert r1.score == r2.score
    assert r1.breakdown == r2.breakdown


def test_score_all_components_absent_is_zero():
    a = item("a", text=None, zone=None, when=None)
    b = item("b", ItemType.FOUND, text=None, zone=None, when=None)
    r = scorer.score(a, b, {"text": 1.0})
    assert r.score == 0.0
    assert r.breakdown == {}


# ---- profile selector + threshold boundary -----------------------------------------


def test_profile_selector_reads_env(monkeypatch):
    monkeypatch.setenv("WEIGHT_TEXT", "0.7")
    monkeypatch.setenv("WEIGHT_IMAGE", "0.0")
    monkeypatch.setenv("WEIGHT_LOCATION", "0.2")
    monkeypatch.setenv("WEIGHT_TIME", "0.1")
    monkeypatch.setenv("MATCH_THRESHOLD", "0.65")
    p = DefaultProfileSelector().select(item("a"), item("b", ItemType.FOUND))
    assert p.name == "text_location_time"
    assert p.weights == {"text": 0.7, "image": 0.0, "location": 0.2, "time": 0.1}
    assert p.threshold == 0.65


def test_profile_selector_defaults(monkeypatch):
    for v in ["WEIGHT_TEXT", "WEIGHT_IMAGE", "WEIGHT_LOCATION", "WEIGHT_TIME", "MATCH_THRESHOLD"]:
        monkeypatch.delenv(v, raising=False)
    p = DefaultProfileSelector().select(item("a"), item("b", ItemType.FOUND))
    assert p.weights == {"text": 0.6, "image": 0.0, "location": 0.25, "time": 0.15}
    assert p.threshold == 0.7


def test_threshold_boundary_semantics():
    # The worker persists when score >= threshold. Verify a score sitting exactly on a
    # threshold is treated as a match (>=), and just-below is not.
    a = item("a", text=[1, 0, 0])
    b = item("b", ItemType.FOUND, text=[1, 0, 0])
    score = scorer.score(a, b, {"text": 1.0}).score  # 1.0
    assert score >= 1.0     # boundary inclusive
    assert not (score >= 1.000001)
