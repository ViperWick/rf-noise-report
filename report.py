#!/usr/bin/env python3
"""One-click noise-log report demo (synthetic data only).

Public anonymized form of an internal Excel VBA workflow:
read many LTE/5G noise logs -> charts + a customer-ready summary.
No real customer or employer data is included.
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

try:
    import matplotlib.pyplot as plt
except ImportError as e:  # pragma: no cover
    raise SystemExit("Install matplotlib: pip install matplotlib") from e


def load_rows(path: Path) -> list[dict]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def summarize(rows: list[dict]) -> dict[str, dict]:
    by_band: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        by_band[r["band"]].append(float(r["peak_spur_dbm"]) - float(r["noise_floor_dbm"]))
    out = {}
    for band, deltas in by_band.items():
        out[band] = {
            "channels": len(deltas),
            "avg_spur_above_floor_db": round(sum(deltas) / len(deltas), 2),
            "max_spur_above_floor_db": round(max(deltas), 2),
        }
    return out


def write_charts(rows: list[dict], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    by_band: dict[str, list[tuple[float, float, float]]] = defaultdict(list)
    for r in rows:
        by_band[r["band"]].append(
            (float(r["freq_mhz"]), float(r["noise_floor_dbm"]), float(r["peak_spur_dbm"]))
        )
    paths = []
    for band, pts in by_band.items():
        pts.sort()
        freq = [p[0] for p in pts]
        floor = [p[1] for p in pts]
        peak = [p[2] for p in pts]
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.plot(freq, floor, label="noise floor (dBm)")
        ax.plot(freq, peak, label="peak spur (dBm)")
        ax.set_title(f"{band}: synthetic noise scan")
        ax.set_xlabel("Frequency (MHz)")
        ax.set_ylabel("Level (dBm)")
        ax.legend()
        ax.grid(True, alpha=0.3)
        path = out_dir / f"{band}_noise_chart.png"
        fig.tight_layout()
        fig.savefig(path, dpi=120)
        plt.close(fig)
        paths.append(path)
    return paths


def write_markdown(summary: dict[str, dict], chart_paths: list[Path], out_path: Path) -> None:
    lines = [
        "# RF noise report (synthetic demo)",
        "",
        "Generated in one click from sample LTE/5G noise logs.",
        "This public demo uses only synthetic data.",
        "",
        "## Summary by band",
        "",
        "| Band | Channels | Avg spur above floor (dB) | Max spur above floor (dB) |",
        "| --- | ---: | ---: | ---: |",
    ]
    for band, s in sorted(summary.items()):
        lines.append(
            f"| {band} | {s['channels']} | {s['avg_spur_above_floor_db']} | {s['max_spur_above_floor_db']} |"
        )
    lines += ["", "## Charts", ""]
    for p in chart_paths:
        lines.append(f"- `{p.name}`")
    lines += [
        "",
        "## What this proves",
        "",
        "Problem: hundreds of noise-test log lines are hard to hand to a customer.",
        "Need: band, channel, frequency, floor, and spur in one place.",
        "Result: charts + a short table a customer can read without opening raw logs.",
        "",
    ]
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--input",
        type=Path,
        default=Path(__file__).parent / "sample_data" / "synthetic_noise_logs.csv",
    )
    ap.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).parent / "output",
    )
    args = ap.parse_args()
    rows = load_rows(args.input)
    summary = summarize(rows)
    charts = write_charts(rows, args.output_dir / "charts")
    report = args.output_dir / "report.md"
    write_markdown(summary, charts, report)
    print(f"Wrote {report}")
    for c in charts:
        print(f"Wrote {c}")


if __name__ == "__main__":
    main()
