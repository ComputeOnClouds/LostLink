"""Run the matching evaluation over a dataset: one CSV and one precision-vs-recall figure.

Offline: pure scoring over a dataset with cached vecText (generate.py or
generate_sample.py produces one). For every weight variant and threshold it writes
eval/output/metrics.csv, and plots alert precision against true-match recall in
eval/output/precision_recall.png.

Usage:
    python3 run_eval.py [path/to/dataset.json]  (default: data/generated/dataset.json)
    THRESHOLDS=0.6,0.7,0.8 python3 run_eval.py ...   (default: 0.40 to 0.95 in steps of 0.05)
"""

from __future__ import annotations

import csv
import os
import sys

from harness import VARIANTS, evaluate, load_dataset

COLS = ["variant", "threshold", "hit_at_1", "recall_at_5", "mrr", "alert_precision",
        "true_match_recall", "incorrect_alerts", "false_alert_rate"]
LABELS = {"text_only": "Text only", "text_location": "Text + location",
          "text_time": "Text + time", "text_location_time": "Text + location + time"}
# Categorical colours in fixed order, plus a marker shape each so lines are not told apart by colour alone.
STYLE = {"text_only": ("#2a78d6", "o"), "text_location": ("#eb6834", "s"),
         "text_time": ("#1baf7a", "^"), "text_location_time": ("#eda100", "D")}


def plot(reports: list, subtitle: str, path: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    surface, ink, muted, grid = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3de"
    fig, ax = plt.subplots(figsize=(7.5, 5.2), dpi=200, facecolor=surface)
    ax.set_facecolor(surface)
    for variant in VARIANTS:
        rows = sorted((r for r in reports if r.variant == variant), key=lambda r: r.threshold)
        colour, marker = STYLE[variant]
        ax.plot([r.true_match_recall for r in rows], [r.alert_precision for r in rows], color=colour,
                linewidth=1.6, marker=marker, markersize=6, markeredgecolor=surface, markeredgewidth=1.0,
                label=LABELS[variant], zorder=3)
        if variant == "text_location_time":  # label thresholds on one line only, to keep it readable
            for r in rows:
                if r.threshold >= 0.7:
                    dx, dy, ha = (5, -11, "left") if r.threshold in (0.75, 0.8, 0.85) else (-7, 5, "right")
                    ax.annotate(f"{r.threshold:.2f}", (r.true_match_recall, r.alert_precision), xytext=(dx, dy),
                                textcoords="offset points", ha=ha, fontsize=7.5, color=muted)
    lowest = min(r.true_match_recall for r in reports)
    ax.set_xlim(max(0.0, round(lowest - 0.1, 1)), 1.03)
    ax.set_ylim(-0.02, 1.08)
    ax.set_xlabel("True-match recall (share of true matches that alert)", color=muted, fontsize=9)
    ax.set_ylabel("Alert precision (share of alerts that are the true match)", color=muted, fontsize=9)
    ax.text(0, 1.115, "Alert precision vs true-match recall", transform=ax.transAxes, color=ink, fontsize=11,
            va="bottom")
    ax.text(0, 1.025, subtitle, transform=ax.transAxes, color=muted, fontsize=8, va="bottom", linespacing=1.5)
    ax.grid(color=grid, linewidth=0.6, zorder=0)
    ax.tick_params(colors=muted, labelsize=8, length=0)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(grid)
    ax.legend(loc="lower left", frameon=False, fontsize=8.5, labelcolor=ink)
    fig.tight_layout()
    fig.savefig(path, facecolor=surface)
    plt.close(fig)


def main():
    default = os.path.join(os.path.dirname(__file__), "data", "generated", "dataset.json")
    path = sys.argv[1] if len(sys.argv) > 1 else default
    if not os.path.exists(path):
        print(f"Dataset not found: {path}\nRun generate.py or generate_sample.py first.")
        sys.exit(1)

    dataset = load_dataset(path)
    default_thresholds = ",".join(f"{0.40 + 0.05 * i:.2f}" for i in range(12))
    thresholds = [float(t) for t in os.environ.get("THRESHOLDS", default_thresholds).split(",")]
    reports = [r for t in thresholds for r in evaluate(dataset, threshold=t)]
    reports.sort(key=lambda r: (list(VARIANTS).index(r.variant), r.threshold))

    out_dir = os.path.join(os.path.dirname(__file__), "output")
    os.makedirs(out_dir, exist_ok=True)

    print(f"\nDataset: {len(dataset['lost'])} lost, {len(dataset['found'])} found\n")
    print("  ".join(f"{c:>18}" for c in COLS))
    for r in reports:
        print("  ".join(f"{str(getattr(r, c)):>18}" for c in COLS))

    with open(os.path.join(out_dir, "metrics.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLS)
        for r in reports:
            w.writerow([getattr(r, c) for c in COLS])
    n_lost, n_found = len(dataset["lost"]), len(dataset["found"])
    plot(reports, f"{n_lost} lost / {n_found} found; one point per threshold from {min(thresholds):.2f} to "
                  f"{max(thresholds):.2f}.\nA higher threshold moves a line up and left. "
                  f"Numbers: thresholds on the text + location + time line.",
         os.path.join(out_dir, "precision_recall.png"))
    print(f"\nWrote {out_dir}/metrics.csv and precision_recall.png")


if __name__ == "__main__":
    main()
