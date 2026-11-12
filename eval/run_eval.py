"""Run the matching evaluation over a dataset: one CSV and three figures.

Offline: pure scoring over a dataset with cached vecText (generate.py or
generate_sample.py produces one). For every weight variant and threshold it writes
eval/output/metrics.csv, plus:
  precision_recall.png      alert precision against true-match recall, one point per threshold
  metrics_by_threshold.png  alert precision and false-alert rate against the threshold
  ranking.png               Hit@1, Recall@5 and MRR (threshold-free)

Usage:
    python3 run_eval.py [path/to/dataset.json]  (default: data/generated/dataset.json)
    THRESHOLDS=0.6,0.7,0.8 python3 run_eval.py ...   (default: 0.40 to 0.95 in steps of 0.05)
"""

from __future__ import annotations

import csv
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from harness import VARIANTS, evaluate, load_dataset  # noqa: E402

COLS = ["variant", "threshold", "hit_at_1", "recall_at_5", "mrr", "alert_precision",
        "true_match_recall", "incorrect_alerts", "false_alert_rate"]
LABELS = {"text_only": "Text only", "text_location": "Text + location",
          "text_time": "Text + time", "text_location_time": "Text + location + time"}
# Categorical colours in fixed order, plus a marker shape each so lines are not told apart by colour alone.
STYLE = {"text_only": ("#2a78d6", "o"), "text_location": ("#eb6834", "s"),
         "text_time": ("#1baf7a", "^"), "text_location_time": ("#eda100", "D")}
SURFACE, INK, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3de"
# Thresholds annotated on the text + location + time line: label offset (points) and alignment.
LABELLED = {0.7: (14, 22, "left"), 0.8: (16, 10, "left"), 0.9: (-14, 12, "right")}
RANKING = [("hit_at_1", "Hit@1"), ("recall_at_5", "Recall@5"), ("mrr", "MRR")]
PANELS = [("alert_precision", "Alert precision"), ("false_alert_rate", "False-alert rate")]


def series(reports: list, variant: str) -> list:
    return sorted((r for r in reports if r.variant == variant), key=lambda r: r.threshold)


def line(ax, xs: list, ys: list, variant: str, markersize: float = 6) -> None:
    colour, marker = STYLE[variant]
    ax.plot(xs, ys, color=colour, linewidth=1.6, marker=marker, markersize=markersize, markeredgecolor=SURFACE,
            markeredgewidth=1.0, label=LABELS[variant], zorder=3)


def style(ax, xlabel: str = "", ylabel: str = "", grid_axis: str = "both") -> None:
    ax.set_facecolor(SURFACE)
    ax.set_xlabel(xlabel, color=MUTED, fontsize=9)
    ax.set_ylabel(ylabel, color=MUTED, fontsize=9)
    ax.grid(axis=grid_axis, color=GRID, linewidth=0.6, zorder=0)
    ax.tick_params(colors=MUTED, labelsize=8, length=0)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)


def save(fig, title: str, subtitle: str, path: str) -> None:
    """Title, subtitle and one shared legend row above the plots, then write the PNG."""
    h = fig.get_figheight()
    fig.text(0.012, 1 - 0.12 / h, title, color=INK, fontsize=11, va="top")
    fig.text(0.012, 1 - 0.38 / h, subtitle, color=MUTED, fontsize=8, va="top")
    handles, labels = fig.axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper left", bbox_to_anchor=(0.004, 1 - 0.54 / h), ncol=len(labels),
               frameon=False, fontsize=8.5, labelcolor=INK)
    fig.tight_layout(rect=(0, 0, 1, 1 - 0.88 / h))
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


def plot_precision_recall(reports: list, subtitle: str, path: str) -> None:
    fig, ax = plt.subplots(figsize=(7.5, 5.6), dpi=200, facecolor=SURFACE)
    for variant in VARIANTS:
        rows = series(reports, variant)
        line(ax, [r.true_match_recall for r in rows], [r.alert_precision for r in rows], variant)
    for r in series(reports, "text_location_time"):  # a few thresholds on one line only, to keep it readable
        if r.threshold in LABELLED:
            dx, dy, ha = LABELLED[r.threshold]
            ax.annotate(f"{r.threshold:.2f}", (r.true_match_recall, r.alert_precision), xytext=(dx, dy),
                        textcoords="offset points", ha=ha, va="center", fontsize=7.5, color=MUTED,
                        arrowprops={"arrowstyle": "-", "color": MUTED, "linewidth": 0.6, "shrinkB": 4})
    lowest = min(r.true_match_recall for r in reports)
    ax.set_xlim(max(0.0, round(lowest - 0.1, 1)), 1.03)
    ax.set_ylim(-0.02, 1.08)
    style(ax, "True-match notification recall", "Alert precision")
    save(fig, "Alert precision vs true-match notification recall", subtitle, path)


def plot_thresholds(reports: list, subtitle: str, path: str) -> None:
    fig, axes = plt.subplots(1, len(PANELS), figsize=(7.5, 4.2), dpi=200, facecolor=SURFACE, sharex=True)
    for ax, (key, name) in zip(axes, PANELS):
        for variant in VARIANTS:
            rows = series(reports, variant)
            line(ax, [r.threshold for r in rows], [getattr(r, key) for r in rows], variant, markersize=4)
        ax.set_ylim(-0.03, 1.05)
        ax.set_title(name, loc="left", color=INK, fontsize=9)
        style(ax, "Threshold")
    save(fig, "Alert metrics by threshold", subtitle, path)


def plot_ranking(reports: list, subtitle: str, path: str) -> None:
    fig, ax = plt.subplots(figsize=(7.5, 4.6), dpi=200, facecolor=SURFACE)
    width = 0.2
    for i, variant in enumerate(VARIANTS):
        r = series(reports, variant)[0]  # ranking metrics are the same at every threshold
        bars = ax.bar([m + (i - 1.5) * width for m in range(len(RANKING))], [getattr(r, key) for key, _ in RANKING],
                      width=width * 0.9, color=STYLE[variant][0], label=LABELS[variant], zorder=3)
        ax.bar_label(bars, fmt="%.2f", padding=2, fontsize=7.5, color=MUTED)
    ax.set_xticks(range(len(RANKING)), [name for _, name in RANKING])
    ax.set_ylim(0, 1.1)
    style(ax, ylabel="Score (0 to 1)", grid_axis="y")
    ax.tick_params(axis="x", labelsize=9, colors=INK)
    save(fig, "Ranking quality by configuration", subtitle, path)


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

    size = f"{len(dataset['lost'])} lost / {len(dataset['found'])} found"
    span = f"one point per threshold, {min(thresholds):.2f} to {max(thresholds):.2f}"
    n_true = sum(1 for rec in dataset["lost"] if rec.get("truth"))
    plot_precision_recall(reports, f"{size}; {span}. Labels: thresholds on Text + location + time.",
                          os.path.join(out_dir, "precision_recall.png"))
    plot_thresholds(reports, f"{size}; {span}. Lines overlap where configurations give the same value.",
                    os.path.join(out_dir, "metrics_by_threshold.png"))
    plot_ranking(reports, f"{size}; over the {n_true} lost reports with a true match, using the full ranked "
                          f"list (no threshold).", os.path.join(out_dir, "ranking.png"))
    print(f"\nWrote {out_dir}/metrics.csv, precision_recall.png, metrics_by_threshold.png and ranking.png")


if __name__ == "__main__":
    main()
