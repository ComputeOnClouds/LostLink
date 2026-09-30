#!/usr/bin/env bash
# Task 9: prove the Scorer/ProfileSelector/models are pure (no boto3 needed), so the
# eval harness (Task 13) can import and sweep them without AWS deps installed.
set -euo pipefail
cd "$(dirname "$0")/../backend"

# Use a throwaway venv with ONLY the standard library (no boto3/numpy) to be sure the
# pure scoring path has zero AWS dependency.
TMPVENV=$(mktemp -d)/purevenv
python3 -m venv "$TMPVENV"
# shellcheck disable=SC1091
. "$TMPVENV/bin/activate"
# deliberately install nothing

python3 - <<'PY'
import sys
# Fail loudly if boto3 sneaks in via import side-effects.
import builtins
_real_import = builtins.__import__
def guard(name, *a, **k):
    if name.split(".")[0] == "boto3":
        raise AssertionError("boto3 was imported by the pure scoring path!")
    return _real_import(name, *a, **k)
builtins.__import__ = guard

from pipeline.impl.scorer import BlendedScorer
from pipeline.impl.profile import DefaultProfileSelector
from pipeline.models import Item, ItemType, VectorMap

a = Item(item_id="a", item_type=ItemType.LOST, organisation_id="o", owner_id="u",
         description="d", location_zone="z1", event_time="2026-09-29T10:00:00+00:00",
         vectors=VectorMap(text=[1.0, 0.0, 0.0]))
b = Item(item_id="b", item_type=ItemType.FOUND, organisation_id="o2", owner_id="s",
         description="d", location_zone="z1", event_time="2026-09-29T11:00:00+00:00",
         vectors=VectorMap(text=[1.0, 0.0, 0.0]))
p = DefaultProfileSelector().select(a, b)
r = BlendedScorer().score(a, b, p.weights)
assert 0.0 <= r.score <= 1.0
print(f"pure scoring OK (no boto3), score={r.score}, breakdown={r.breakdown}")
PY

deactivate
rm -rf "$(dirname "$TMPVENV")"
