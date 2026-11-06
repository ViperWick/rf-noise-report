#!/usr/bin/env python3
"""Write synthetic instrument RX-noise CSVs.

The logs imitate a per-band instrument dump: two rows per channel (RxId 0 main,
RxId 1 aux) and 100 RX power samples. Labels are intentionally loose so the
format bridge has Mode/Band cleanup to do. One Loaded aux point on B7 is left
out so the bridge has to pad the shared channel axis.

Nothing here is a measured unit, a customer log, or a real limit.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import math
import random
from datetime import datetime, timedelta
from pathlib import Path

from convert import N_SAMPLES, RAW_COLUMNS, RAW_RX_COLUMNS


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (pct / 100.0)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    weight = rank - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def seed_from(parts: tuple[object, ...]) -> int:
    digest = hashlib.sha256("|".join(map(str, parts)).encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def lte_channels(band: str, freqs_mhz: list[float]) -> list[tuple[int, float]]:
    origin = {"B3": (1805.0, 1200), "B7": (2620.0, 2750), "B12": (729.0, 5010)}[band]
    start_mhz, start_earfcn = origin
    channels = []
    for freq in freqs_mhz:
        earfcn = int(round(start_earfcn + (freq - start_mhz) * 10))
        channels.append((earfcn, float(freq)))
    return channels


def nr_channels(freqs_mhz: list[float]) -> list[tuple[int, float]]:
    channels = []
    for freq in freqs_mhz:
        nrarfcn = int(round(600000 + (freq - 3000.0) / 0.015))
        channels.append((nrarfcn, float(freq)))
    return channels


# Loaded B12 is shifted high enough to fail the illustrative limit table.
# The other bands stay quieter than those same limits.
PLANS = [
    {
        "file_prefix": "LTE_B3",
        "mode": "LTE",
        "band": "B3",
        "bw": 20,
        "num_rb": 100,
        "baseline_dbm": -96.4,
        "loaded_offset_db": 0.60,
        "phase": 0.2,
        "channels": lte_channels(
            "B3", [1805, 1815, 1825, 1835, 1845, 1855, 1865, 1875]
        ),
    },
    {
        "file_prefix": "LTE_B7",
        "mode": "LTE",
        "band": "B7",
        "bw": 20,
        "num_rb": 100,
        "baseline_dbm": -95.8,
        "loaded_offset_db": 0.90,
        "phase": 1.1,
        "channels": lte_channels(
            "B7", [2620, 2630, 2640, 2650, 2660, 2670, 2680, 2689]
        ),
    },
    {
        "file_prefix": "LTE_B12",
        "mode": "LTE",
        "band": "B12",
        "bw": 10,
        "num_rb": 50,
        "baseline_dbm": -96.6,
        "loaded_offset_db": 2.40,
        "phase": 2.0,
        "channels": lte_channels("B12", [729, 732, 735, 738, 741, 744]),
    },
    {
        "file_prefix": "NR_n78",
        "mode": "NR",
        "band": "n78",
        "bw": 100,
        "num_rb": 273,
        "baseline_dbm": -95.2,
        "loaded_offset_db": 1.10,
        "phase": 0.6,
        "channels": nr_channels([3450, 3480, 3510, 3540, 3570, 3600, 3630, 3660]),
    },
]

MODE_LABELS = {
    "LTE": ["LTE", "lte-fdd", "LTE FDD"],
    "NR": ["5GNR", "nr-sa", "NR"],
}
BAND_LABELS = {
    "B3": ["Band 3", "b3", "3"],
    "B7": ["B7", "band 7", "7"],
    "B12": ["12", "Band 12", "b12"],
    "n78": ["N78", "Band n78", "n78"],
}


def row_center(plan: dict, config: str, rx_id: int, index: int) -> float:
    center = plan["baseline_dbm"]
    if config == "Loaded":
        center += plan["loaded_offset_db"]
    if rx_id == 1:
        center += 0.15
    count = len(plan["channels"])
    span = 0.0 if count < 2 else (index / (count - 1) - 0.5)
    center += span * 0.30
    center += 0.10 * math.sin(index * 1.7 + plan["phase"])
    return center


def should_skip(plan: dict, config: str, channel: int, rx_id: int) -> bool:
    """Leave a single hole so axis padding is visible in the bridge output."""
    middle = plan["channels"][len(plan["channels"]) // 2][0]
    return (
        plan["band"] == "B7"
        and config == "Loaded"
        and rx_id == 1
        and channel == middle
    )


def build_row(
    plan: dict,
    config: str,
    index: int,
    channel: int,
    frequency: float,
    rx_id: int,
    stamp: str,
) -> dict[str, str]:
    center = row_center(plan, config, rx_id, index)
    rng = random.Random(seed_from((plan["band"], config, channel, rx_id, "samples")))
    samples = [round(center + rng.uniform(-0.30, 0.30), 2) for _ in range(N_SAMPLES)]
    mean = sum(samples) / len(samples)
    row = {
        "Time": stamp,
        "Mode": MODE_LABELS[plan["mode"]][index % 3],
        "Band": BAND_LABELS[plan["band"]][index % 3],
        "BW": str(plan["bw"]),
        "Channel": str(channel),
        "Frequency": f"{frequency:.1f}",
        "StartRB": "0",
        "NumRB": str(plan["num_rb"]),
        "TARGET_TX_PWR": "23" if config == "Loaded" else "0",
        "RxId": str(rx_id),
        "RxAGC_Mean": f"{mean:.2f}",
        "RxAGC_95thPercentile": f"{percentile(samples, 95):.2f}",
        "RxAGC_Max": f"{max(samples):.2f}",
    }
    for column, sample in zip(RAW_RX_COLUMNS, samples):
        row[column] = f"{sample:.2f}"
    return row


def write_raw(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RAW_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def generate(raw_dir: Path) -> list[Path]:
    written: list[Path] = []
    skipped: list[str] = []
    stamp = datetime(2026, 3, 15, 9, 0, 0)
    for plan in PLANS:
        for config in ("Baseline", "Loaded"):
            rows: list[dict[str, str]] = []
            for index, (channel, frequency) in enumerate(plan["channels"]):
                for rx_id in (0, 1):
                    stamp += timedelta(seconds=2)
                    if should_skip(plan, config, channel, rx_id):
                        skipped.append(
                            f"{plan['band']} {config} channel {channel} RxId {rx_id}"
                        )
                        continue
                    rows.append(
                        build_row(
                            plan,
                            config,
                            index,
                            channel,
                            frequency,
                            rx_id,
                            stamp.strftime("%Y-%m-%d %H:%M:%S"),
                        )
                    )
            path = raw_dir / f"{plan['file_prefix']}_{config}.csv"
            write_raw(path, rows)
            written.append(path)
    print(f"Wrote {len(written)} synthetic raw files to {raw_dir}")
    for item in skipped:
        print(f"Left out one point for the bridge to pad: {item}")
    return written


def main() -> None:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=root / "sample_data" / "raw")
    args = parser.parse_args()
    generate(args.raw_dir)


if __name__ == "__main__":
    main()
