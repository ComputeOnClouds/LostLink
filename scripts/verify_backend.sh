#!/usr/bin/env bash
# Task 1 verification: pipeline package imports and scaffold smoke tests pass.
set -euo pipefail
cd "$(dirname "$0")/../backend"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
. .venv/bin/activate
pip install --quiet -r requirements-dev.txt

python3 -c 'import pipeline; print("pipeline import OK")'
python3 -m pytest -q
