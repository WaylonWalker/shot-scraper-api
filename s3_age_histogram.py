#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "boto3",
#   "matplotlib",
#   "numpy",
# ]
# ///

from __future__ import annotations

import sys
from collections import Counter
from datetime import timezone, date

import boto3
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np


def parse_bucket(url: str) -> str:
    if not url.startswith("s3://"):
        raise SystemExit("Bucket must be in the form s3://bucket-name")
    return url.removeprefix("s3://").rstrip("/")


def collect_dates(bucket: str) -> Counter[date]:
    s3 = boto3.client("s3")
    paginator = s3.get_paginator("list_objects_v2")

    counts: Counter[date] = Counter()

    for page in paginator.paginate(Bucket=bucket):
        for obj in page.get("Contents", []):
            d = obj["LastModified"].astimezone(timezone.utc).date()
            counts[d] += 1

    return counts


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: s3_date_histogram.py s3://bucket")

    bucket = parse_bucket(sys.argv[1])
    print(f"Scanning bucket: {bucket}")

    counts = collect_dates(bucket)
    if not counts:
        print("No objects found.")
        return

    dates = sorted(counts)
    values = [counts[d] for d in dates]
    values_arr = np.array(values, dtype=float)

    # Top 4 days by count
    top_days = counts.most_common(4)

    # ---------- Prettier theme ----------
    plt.style.use("fivethirtyeight")
    fig, ax = plt.subplots(figsize=(14, 7))
    fig.patch.set_facecolor("#020617")   # dark background
    ax.set_facecolor("#020617")

    # Slightly softer bar color
    bar_color = "#60a5fa"  # Tailwind-ish sky-500

    ax.bar(dates, values, width=1.0, align="center", color=bar_color, edgecolor="#1d4ed8")

    ax.set_title(f"S3 Objects by Date – {bucket}", fontsize=16, pad=16, color="#e5e7eb")
    ax.set_xlabel("Date", fontsize=12, color="#e5e7eb")
    ax.set_ylabel("Number of objects", fontsize=12, color="#e5e7eb")

    # Tick styling
    ax.tick_params(axis="x", colors="#e5e7eb", labelrotation=0)
    ax.tick_params(axis="y", colors="#e5e7eb")
    for spine in ax.spines.values():
        spine.set_color("#4b5563")

    # Date formatting
    locator = mdates.AutoDateLocator()
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))

    # ---------- Annotate top 4 days ----------
    for d, count in top_days:
        ax.scatter([d], [count], zorder=5, color="#facc15")  # yellow dot
        ax.annotate(
            f"{d.isoformat()}\n{count}",
            xy=(d, count),
            xytext=(0, 10),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=9,
            color="#e5e7eb",
            arrowprops=dict(arrowstyle="-", linewidth=0.8, color="#9ca3af"),
        )

    # ---------- Summary statistics (top-right) ----------
    stats_lines = [
        f"Total objects: {int(values_arr.sum())}",
        f"Days with uploads: {len(values_arr)}",
        f"Avg / day: {values_arr.mean():.1f}",
        f"Median / day: {np.median(values_arr):.0f}",
        f"Range:\n{dates[0].isoformat()} → {dates[-1].isoformat()}",
    ]
    stats_text = "\n".join(stats_lines)

    ax.text(
        0.995,
        0.995,
        stats_text,
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=9,
        color="#e5e7eb",
        bbox=dict(
            boxstyle="round,pad=0.5",
            facecolor="#020617",
            edgecolor="#4b5563",
            alpha=0.9,
        ),
    )

    fig.autofmt_xdate()
    fig.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()

