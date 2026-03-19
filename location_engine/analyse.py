"""
Data analysis and visualisation for localization test results.

Usage:
  python analyse.py 4mTest_with_fallback.csv 2mTest_with_fallback.csv
  python analyse.py 4mTest_with_fallback.csv   # single file also works
"""

import sys
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np


def load(path):
    df = pd.read_csv(path)
    df["pos_label"] = df.apply(lambda r: f"({r.actual_x:.0f},{r.actual_y:.0f})", axis=1)
    return df


def summary(df, label):
    print(f"\n{'='*50}")
    print(f" {label}")
    print(f"{'='*50}")
    print(f"  Total rows : {len(df)}")

    for algo, method_col, fallback_col, err_col in [
        ("Heron", "heron_method", "heron_fallback", "heron_err"),
        ("Tri",   "tri_method",   "tri_fallback",   "tri_err"),
    ]:
        fb = (df[fallback_col] == "yes").sum()
        print(f"\n  {algo}:")
        print(f"    Fallback rate : {fb}/{len(df)} ({100*fb/len(df):.0f}%)")
        print(f"    Methods used  : {df[method_col].value_counts().to_dict()}")
        valid = df[err_col].dropna()
        if len(valid):
            print(f"    Mean error    : {valid.mean():.3f}m")
            print(f"    Median error  : {valid.median():.3f}m")
            print(f"    Max error     : {valid.max():.3f}m")

    print(f"\n  Per-position mean error:")
    grouped = df.groupby("pos_label")[["heron_err", "tri_err"]].mean()
    print(grouped.to_string())


def plot_positions(df, label, ax):
    """Scatter: actual vs heron vs tri estimates."""
    positions = df["pos_label"].unique()
    colors = plt.cm.tab10(np.linspace(0, 1, len(positions)))
    color_map = dict(zip(positions, colors))

    for _, row in df.iterrows():
        c = color_map[row["pos_label"]]
        ax.scatter(row["actual_x"], row["actual_y"], marker="*", s=200, color=c, zorder=5)
        ax.scatter(row["heron_x"], row["heron_y"], marker="o", s=40, color=c, alpha=0.5)
        ax.scatter(row["tri_x"],   row["tri_y"],   marker="^", s=40, color=c, alpha=0.5)

    legend = [
        mpatches.Patch(color="gray", label="★ Actual"),
        plt.Line2D([0],[0], marker="o", color="w", markerfacecolor="gray", markersize=8, label="● Heron est."),
        plt.Line2D([0],[0], marker="^", color="w", markerfacecolor="gray", markersize=8, label="▲ Tri est."),
    ]
    for pos, c in color_map.items():
        legend.append(mpatches.Patch(color=c, label=pos))

    ax.legend(handles=legend, fontsize=7, loc="upper left")
    ax.set_title(f"{label} — Estimated vs Actual positions")
    ax.set_xlabel("X (m)")
    ax.set_ylabel("Y (m)")
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.set_aspect("equal")


def plot_errors(df, label, ax):
    """Bar chart: mean error per position, heron vs tri."""
    grouped = df.groupby("pos_label")[["heron_err", "tri_err"]].mean()
    x = np.arange(len(grouped))
    width = 0.35
    ax.bar(x - width/2, grouped["heron_err"], width, label="Heron", color="steelblue")
    ax.bar(x + width/2, grouped["tri_err"],   width, label="Tri",   color="coral")
    ax.set_xticks(x)
    ax.set_xticklabels(grouped.index, rotation=15)
    ax.set_ylabel("Mean error (m)")
    ax.set_title(f"{label} — Mean error by position")
    ax.legend()
    ax.grid(axis="y", linestyle="--", alpha=0.4)


def plot_fallback(df, label, ax):
    """Stacked bar: fallback vs no-fallback counts per position."""
    grouped = df.groupby("pos_label").apply(
        lambda g: pd.Series({
            "heron_no":  (g["heron_fallback"] == "no").sum(),
            "heron_yes": (g["heron_fallback"] == "yes").sum(),
            "tri_no":    (g["tri_fallback"]   == "no").sum(),
            "tri_yes":   (g["tri_fallback"]   == "yes").sum(),
        })
    )
    x = np.arange(len(grouped))
    width = 0.35
    ax.bar(x - width/2, grouped["heron_no"],  width, label="Heron primary",  color="steelblue")
    ax.bar(x - width/2, grouped["heron_yes"], width, bottom=grouped["heron_no"],  label="Heron fallback", color="steelblue", alpha=0.3, hatch="//")
    ax.bar(x + width/2, grouped["tri_no"],    width, label="Tri primary",    color="coral")
    ax.bar(x + width/2, grouped["tri_yes"],   width, bottom=grouped["tri_no"],    label="Tri fallback",   color="coral",     alpha=0.3, hatch="//")
    ax.set_xticks(x)
    ax.set_xticklabels(grouped.index, rotation=15)
    ax.set_ylabel("Count")
    ax.set_title(f"{label} — Fallback usage by position")
    ax.legend(fontsize=8)
    ax.grid(axis="y", linestyle="--", alpha=0.4)


def plot_error_timeline(df, label, ax):
    """Line plot: error over time (index), heron vs tri."""
    ax.plot(df["heron_err"].values, label="Heron", color="steelblue", marker="o", markersize=3)
    ax.plot(df["tri_err"].values,   label="Tri",   color="coral",     marker="^", markersize=3)
    ax.set_xlabel("Sample index")
    ax.set_ylabel("Error (m)")
    ax.set_title(f"{label} — Error over time")
    ax.legend()
    ax.grid(linestyle="--", alpha=0.4)


def analyse(path, label):
    df = load(path)
    summary(df, label)

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle(label, fontsize=14, fontweight="bold")

    plot_positions(df, label, axes[0][0])
    plot_errors(df, label, axes[0][1])
    plot_fallback(df, label, axes[1][0])
    plot_error_timeline(df, label, axes[1][1])

    plt.tight_layout()
    out = path.replace(".csv", "_analysis.png")
    plt.savefig(out, dpi=150)
    print(f"\n  Saved plot → {out}")
    plt.show()


if __name__ == "__main__":
    files = sys.argv[1:] if len(sys.argv) > 1 else ["4mTest_with_fallback.csv", "2mTest_with_fallback.csv"]
    for f in files:
        label = f.replace("_with_fallback.csv", "").replace(".csv", "")
        analyse(f, label)
