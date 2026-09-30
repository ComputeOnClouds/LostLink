"""Scorer implementation (Task 8 initial; hardened + fully tested in Task 9).

Pure function: no AWS, no retrieval. The evaluation harness imports this directly.

score = w_text*textSim + w_image*imageSim + w_location*spatialSim + w_time*temporalSim

- textSim / imageSim: cosine similarity of the respective vectors, mapped to [0,1].
  Image term is only non-zero when BOTH items carry an image vector, so raising
  ``w_image`` later (Option 2, RATIONALE ADR-003/004) is sufficient to enable it.
- spatialSim: 1.0 if the location zones match, else a configurable low value.
- temporalSim: exponential decay in the absolute time difference (a lost item is more
  likely the found item if they occurred close in time).

Missing components contribute 0 and their weight is dropped from the normaliser so the
score stays in [0,1] regardless of which signals are present.
"""

from __future__ import annotations

import math
from datetime import datetime

from ..interfaces import Scorer
from ..models import Item, MatchResult, VectorMap


def _cosine(a: list[float] | None, b: list[float] | None) -> float | None:
    if not a or not b or len(a) != len(b):
        return None
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return None
    cos = dot / (na * nb)
    # Map cosine [-1,1] -> [0,1].
    return max(0.0, min(1.0, (cos + 1.0) / 2.0))


def _spatial(a: Item, b: Item, mismatch: float = 0.1) -> float | None:
    if not a.location_zone or not b.location_zone:
        return None
    return 1.0 if a.location_zone == b.location_zone else mismatch


def _temporal(a: Item, b: Item, half_life_hours: float = 72.0) -> float | None:
    ta, tb = _parse_time(a.event_time), _parse_time(b.event_time)
    if ta is None or tb is None:
        return None
    hours = abs((ta - tb).total_seconds()) / 3600.0
    # Exponential decay: 1.0 at same time, 0.5 at one half-life apart.
    return math.pow(0.5, hours / half_life_hours)


def _parse_time(s: str | None):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


class BlendedScorer(Scorer):
    def score(self, a: Item, b: Item, weights: dict[str, float]) -> MatchResult:
        components: dict[str, tuple[float, float]] = {}  # name -> (similarity, weight)

        text_sim = _cosine(a.vectors.text, b.vectors.text)
        if text_sim is not None:
            components["text"] = (text_sim, weights.get("text", 0.0))

        image_sim = _cosine(a.vectors.image, b.vectors.image)
        if image_sim is not None:
            components["image"] = (image_sim, weights.get("image", 0.0))

        spatial = _spatial(a, b)
        if spatial is not None:
            components["location"] = (spatial, weights.get("location", 0.0))

        temporal = _temporal(a, b)
        if temporal is not None:
            components["time"] = (temporal, weights.get("time", 0.0))

        # Weighted average over present components (drop absent ones from normaliser).
        total_weight = sum(w for _, w in components.values())
        breakdown = {name: sim for name, (sim, _) in components.items()}
        if total_weight <= 0:
            score = 0.0
        else:
            score = sum(sim * w for sim, w in components.values()) / total_weight

        return MatchResult(
            query_item_id=a.item_id,
            candidate_item_id=b.item_id,
            organisation_id=b.organisation_id,
            score=round(score, 6),
            profile_name="",  # set by the worker from the selected profile
            breakdown={k: round(v, 6) for k, v in breakdown.items()},
        )
