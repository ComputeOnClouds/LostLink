"""ProfileSelector implementation (Task 8 initial; multi-profile hook kept for later).

Today: a single active profile (text + location + time; image weight 0). Weights and
the notification threshold are read from environment variables (set by CDK from
config.ts), so tuning is a redeploy — while the evaluation harness passes weights to the
pure Scorer directly (RATIONALE ADR-005). The image-present profile discussed in
planning is the reserved hook: when Option 2 is enabled, `select` can branch on whether
both items carry an image vector and return a higher-confidence profile.
"""

from __future__ import annotations

import os

from ..interfaces import ProfileSelector
from ..models import Item, Profile


def _f(env: str, default: float) -> float:
    try:
        return float(os.environ.get(env, str(default)))
    except (TypeError, ValueError):
        return default


class DefaultProfileSelector(ProfileSelector):
    def select(self, a: Item, b: Item) -> Profile:
        weights = {
            "text": _f("WEIGHT_TEXT", 0.6),
            "image": _f("WEIGHT_IMAGE", 0.0),  # reserved; Option 2 raises this
            "location": _f("WEIGHT_LOCATION", 0.25),
            "time": _f("WEIGHT_TIME", 0.15),
        }
        threshold = _f("MATCH_THRESHOLD", 0.7)
        return Profile(name="text_location_time", weights=weights, threshold=threshold)
