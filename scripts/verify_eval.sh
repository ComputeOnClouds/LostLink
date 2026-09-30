#!/usr/bin/env bash
# Task 13: run the evaluation harness unit + sanity tests (offline, no AWS) and the
# metric sweep on the committed sample dataset.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -d backend/.venv ]; then python3 -m venv backend/.venv; fi
# shellcheck disable=SC1091
. backend/.venv/bin/activate
pip install --quiet pytest >/dev/null 2>&1 || true

echo "== eval unit + sanity tests =="
( cd eval && python3 -m pytest -q )

echo
echo "== metric sweep on the committed sample dataset =="
( cd eval && python3 run_eval.py data/sample_dataset.json )
