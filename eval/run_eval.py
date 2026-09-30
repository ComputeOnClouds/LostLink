"""Run the matching evaluation over a dataset and emit metric tables (CSV + JSON).

Offline: needs only numpy-free pure scoring. Point at a dataset with cached vecText
(generate.py produces one). Prints a table and writes eval/output/metrics.{csv,json}.

Usage:
    python3 run_eval.py [path/to/dataset.json]  (default: data/generated/dataset.json)
"""

from __future__ import annotations

import csv
import json
import os
import sys

from harness import evaluate, load_dataset


def main():
    default = os.path.join(os.path.dirname(__file__), "data", "generated", "dataset.json")
    path = sys.argv[1] if len(sys.argv) > 1 else default
    if not os.path.exists(path):
        print(f"Dataset not found: {path}\nRun generate.py first (needs Bedrock).")
        sys.exit(1)

    dataset = load_dataset(path)
    threshold = float(os.environ.get("MATCH_THRESHOLD", "0.7"))
    reports = evaluate(dataset, threshold=threshold)

    out_dir = os.path.join(os.path.dirname(__file__), "output")
    os.makedirs(out_dir, exist_ok=True)

    # Console table.
    cols = ["variant", "hit_at_1", "recall_at_5", "mrr",
            "alert_precision", "false_alert_rate", "missed_notification_rate"]
    print(f"\nDataset: {len(dataset['lost'])} lost, {len(dataset['found'])} found; "
          f"threshold={threshold}\n")
    print("  ".join(f"{c:>22}" for c in cols))
    for r in reports:
        print("  ".join(f"{str(getattr(r, c)):>22}" for c in cols))

    # CSV + JSON.
    with open(os.path.join(out_dir, "metrics.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in reports:
            w.writerow([getattr(r, c) for c in cols])
    with open(os.path.join(out_dir, "metrics.json"), "w") as f:
        json.dump([r.__dict__ for r in reports], f, indent=2)
    print(f"\nWrote {out_dir}/metrics.csv and metrics.json")


if __name__ == "__main__":
    main()
