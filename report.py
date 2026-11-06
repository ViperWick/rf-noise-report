#!/usr/bin/env python3
"""One-page RX noise-power report from normalized synthetic logs.

Compares a Baseline unit with a Loaded unit on each band and antenna:
average noise, P90 noise, and the loaded-minus-baseline delta. The verdict
uses the illustrative limit table shipped with the sample. Those limits are
not a real OEM spec.
"""
from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from convert import NORM_RX_COLUMNS, convert_directory, read_normalized


DISCLAIMER = "Illustrative limits, not a real OEM spec."
SERIES = (
    ("Baseline", "main", "#1f4e79", "o"),
    ("Baseline", "aux", "#5b9bd5", "s"),
    ("Loaded", "main", "#c45911", "o"),
    ("Loaded", "aux", "#ed7d31", "s"),
)


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


def q2(value: float) -> float:
    return round(value + 0.0, 2)


@dataclass
class Limit:
    band: str
    max_avg: float
    max_p90: float
    max_delta: float
    note: str


@dataclass
class Verdict:
    band: str
    mode: str
    antenna: str
    baseline_avg: float
    loaded_avg: float
    delta: float
    baseline_p90: float
    loaded_p90: float
    limit: Limit
    result: str
    reasons: list[str]


def load_limits(path: Path) -> dict[str, Limit]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"No limits in {path}")
    limits: dict[str, Limit] = {}
    for row in rows:
        band = row["band"].strip()
        limits[band] = Limit(
            band=band,
            max_avg=float(row["max_avg_noise_dbm"]),
            max_p90=float(row["max_p90_noise_dbm"]),
            max_delta=float(row["max_delta_db"]),
            note=(row.get("note") or "").strip(),
        )
    return limits


def _means_by_series(rows: list[dict[str, str]]) -> dict[tuple[str, str, str], list[tuple[int, float, float]]]:
    grouped: dict[tuple[str, str, str], list[tuple[int, float, float]]] = {}
    for row in rows:
        samples = [row[column] for column in NORM_RX_COLUMNS]
        if row["RowKind"] == "pad" or any(sample == "" for sample in samples):
            mean = None
        else:
            if row["RowKind"] != "meas":
                raise ValueError(f"Unknown RowKind {row['RowKind']!r}")
            mean = sum(float(sample) for sample in samples) / len(samples)
        key = (row["Band"], row["Config"], row["Antenna"])
        grouped.setdefault(key, []).append(
            (int(row["AxisIndex"]), float(row["Frequency"]), mean if mean is not None else math.nan)
        )
    for points in grouped.values():
        points.sort()
    return grouped


def _stats(points: list[tuple[int, float, float]]) -> tuple[float, float]:
    means = [mean for _index, _freq, mean in points if not math.isnan(mean)]
    if not means:
        raise ValueError("A series has no measurements to score")
    return q2(sum(means) / len(means)), q2(percentile(means, 90))


def score(rows: list[dict[str, str]], limits: dict[str, Limit]) -> tuple[list[Verdict], dict]:
    grouped = _means_by_series(rows)
    modes = {row["Band"]: row["Mode"] for row in rows}
    bands = []
    for row in rows:
        if row["Band"] not in bands:
            bands.append(row["Band"])
    verdicts: list[Verdict] = []
    for band in bands:
        if band not in limits:
            raise ValueError(f"No illustrative limit for band {band}")
        limit = limits[band]
        for antenna in ("main", "aux"):
            baseline = _stats(grouped[(band, "Baseline", antenna)])
            loaded = _stats(grouped[(band, "Loaded", antenna)])
            delta = q2(loaded[0] - baseline[0])
            reasons = []
            if loaded[0] > limit.max_avg:
                reasons.append(
                    f"{antenna} average {loaded[0]:.2f} dBm is above the illustrative limit {limit.max_avg:.2f} dBm"
                )
            if loaded[1] > limit.max_p90:
                reasons.append(
                    f"{antenna} P90 {loaded[1]:.2f} dBm is above the illustrative limit {limit.max_p90:.2f} dBm"
                )
            if delta > limit.max_delta:
                reasons.append(
                    f"{antenna} loaded-minus-baseline delta {delta:.2f} dB is above the illustrative limit {limit.max_delta:.2f} dB"
                )
            verdicts.append(
                Verdict(
                    band=band,
                    mode=modes[band],
                    antenna=antenna,
                    baseline_avg=baseline[0],
                    loaded_avg=loaded[0],
                    delta=delta,
                    baseline_p90=baseline[1],
                    loaded_p90=loaded[1],
                    limit=limit,
                    result="Fail" if reasons else "Pass",
                    reasons=reasons,
                )
            )
    return verdicts, grouped


def _draw_band(ax, band: str, mode: str, grouped: dict, limit: Limit) -> None:
    for config, antenna, color, marker in SERIES:
        points = grouped[(band, config, antenna)]
        freqs = [freq for _index, freq, _mean in points]
        means = [mean for _index, _freq, mean in points]
        ax.plot(
            freqs,
            means,
            color=color,
            marker=marker,
            linewidth=1.6,
            markersize=4.5,
            label=f"{config} {antenna}",
        )
    ax.axhline(
        limit.max_avg,
        color="#666666",
        linestyle="--",
        linewidth=1.0,
        label="illustrative avg limit",
    )
    ax.set_title(f"{mode} {band}")
    ax.set_ylabel("Mean RX noise (dBm)")
    ax.set_ylim(-98.2, -92.2)
    ax.grid(True, alpha=0.3)


def write_charts(out_dir: Path, verdicts: list[Verdict], grouped: dict) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.png"):
        stale.unlink()
    bands = []
    for verdict in verdicts:
        if verdict.band not in bands:
            bands.append(verdict.band)
    limits = {verdict.band: verdict.limit for verdict in verdicts}
    modes = {verdict.band: verdict.mode for verdict in verdicts}
    paths: list[Path] = []
    for band in bands:
        fig, ax = plt.subplots(figsize=(8.2, 4.6))
        _draw_band(ax, band, modes[band], grouped, limits[band])
        ax.set_xlabel("Frequency (MHz)")
        ax.legend(loc="best", fontsize=8)
        fig.text(0.01, 0.01, f"Synthetic data. {DISCLAIMER}", fontsize=8, color="#555555")
        fig.tight_layout(rect=(0, 0.04, 1, 1))
        path = out_dir / f"{modes[band]}_{band}_noise.png"
        fig.savefig(path, dpi=120)
        plt.close(fig)
        paths.append(path)

    cols = 1 if len(bands) == 1 else 2
    grid_rows = math.ceil(len(bands) / cols)
    fig, axes = plt.subplots(
        grid_rows,
        cols,
        figsize=(10.5, 3.5 * grid_rows + 1.0),
        sharey=True,
        squeeze=False,
    )
    flat = list(axes.ravel())
    for ax, band in zip(flat, bands):
        _draw_band(ax, band, modes[band], grouped, limits[band])
        ax.set_xlabel("Frequency (MHz)")
    for ax in flat[len(bands) :]:
        ax.set_visible(False)
    handles, labels = flat[0].get_legend_handles_labels()
    fig.suptitle("Synthetic RX noise: Baseline vs Loaded", fontsize=14, y=0.985)
    fig.legend(
        handles,
        labels,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.945),
        ncol=5,
        frameon=False,
    )
    fig.text(0.01, 0.008, f"Synthetic data. {DISCLAIMER}", fontsize=8, color="#555555")
    fig.tight_layout(rect=(0, 0.03, 1, 0.90))
    overview = out_dir / "overview.png"
    fig.savefig(overview, dpi=120)
    plt.close(fig)
    paths.append(overview)
    return paths


def _markdown(verdicts: list[Verdict], chart_paths: list[Path], pad_rows: int) -> str:
    passed = sum(1 for verdict in verdicts if verdict.result == "Pass")
    failed = len(verdicts) - passed
    lines = [
        "# RX noise-power summary (synthetic)",
        "",
        "Instrument logs -> format bridge -> spec check -> one-page summary.",
        "",
        DISCLAIMER,
        "",
        f"Loaded unit: **{passed} pass, {failed} fail**.",
        f"The format bridge padded **{pad_rows}** missing row(s) so each Baseline/Loaded main/aux series shares one channel axis.",
        "",
        "Noise is average RX power in dBm. A less-negative number is a higher noise floor. Delta is Loaded average minus Baseline average.",
        "",
        "| Band | Antenna | Baseline avg (dBm) | Loaded avg (dBm) | Delta (dB) | Baseline P90 | Loaded P90 | Avg limit | P90 limit | Delta limit | Result |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for verdict in verdicts:
        lines.append(
            "| {band} | {antenna} | {bavg:.2f} | {lavg:.2f} | {delta:.2f} | {bp90:.2f} | {lp90:.2f} | {alim:.2f} | {plim:.2f} | {dlim:.2f} | {result} |".format(
                band=verdict.band,
                antenna=verdict.antenna,
                bavg=verdict.baseline_avg,
                lavg=verdict.loaded_avg,
                delta=verdict.delta,
                bp90=verdict.baseline_p90,
                lp90=verdict.loaded_p90,
                alim=verdict.limit.max_avg,
                plim=verdict.limit.max_p90,
                dlim=verdict.limit.max_delta,
                result=verdict.result,
            )
        )
    fails = [verdict for verdict in verdicts if verdict.result == "Fail"]
    if fails:
        lines += ["", "## Fail notes", ""]
        for verdict in fails:
            for reason in verdict.reasons:
                lines.append(f"- {verdict.mode} {verdict.band} {reason}")
    lines += ["", "## Charts", ""]
    for path in chart_paths:
        lines.append(f"- `{path.name}`")
    lines.append("")
    return "\n".join(lines)


def _html(verdicts: list[Verdict], chart_paths: list[Path], pad_rows: int) -> str:
    passed = sum(1 for verdict in verdicts if verdict.result == "Pass")
    failed = len(verdicts) - passed
    body_rows = []
    for verdict in verdicts:
        css = "pass" if verdict.result == "Pass" else "fail"
        body_rows.append(
            "<tr>"
            f"<td class=\"text\">{verdict.band}</td><td class=\"text\">{verdict.antenna}</td>"
            f"<td>{verdict.baseline_avg:.2f}</td><td>{verdict.loaded_avg:.2f}</td>"
            f"<td>{verdict.delta:.2f}</td><td>{verdict.baseline_p90:.2f}</td>"
            f"<td>{verdict.loaded_p90:.2f}</td><td>{verdict.limit.max_avg:.2f}</td>"
            f"<td>{verdict.limit.max_p90:.2f}</td><td>{verdict.limit.max_delta:.2f}</td>"
            f"<td class=\"text {css}\">{verdict.result}</td></tr>"
        )
    notes = []
    for verdict in verdicts:
        for reason in verdict.reasons:
            notes.append(f"<li>{verdict.mode} {verdict.band} {reason}</li>")
    note_block = ""
    if notes:
        note_block = "<h2>Fail notes</h2><ul>" + "".join(notes) + "</ul>"
    images = []
    for path in chart_paths:
        if path.name == "overview.png":
            continue
        images.append(f"<img alt=\"{path.stem} chart\" src=\"charts/{path.name}\">")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>RX noise-power summary (synthetic)</title>
<style>
  body {{ font-family: "Segoe UI", sans-serif; margin: 24px; color: #1b1b1b; }}
  h1 {{ font-size: 22px; margin: 0 0 8px; }}
  p {{ margin: 6px 0; }}
  .banner {{ background: #fff8e6; border: 1px solid #e4d19a; padding: 8px 12px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; margin-top: 12px; }}
  th, td {{ border: 1px solid #d0d0d0; padding: 4px 6px; text-align: right; }}
  .text {{ text-align: left; }}
  th {{ background: #f4f4f4; }}
  .pass {{ color: #0a7a32; font-weight: 650; }}
  .fail {{ color: #b00020; font-weight: 650; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }}
  img {{ width: 100%; height: auto; }}
</style>
</head>
<body>
<h1>RX noise-power summary (synthetic)</h1>
<p>Instrument logs → format bridge → spec check → one-page summary.</p>
<p class="banner">{DISCLAIMER}</p>
<p>Loaded unit: <strong>{passed} pass, {failed} fail</strong>. Padded rows on the shared channel axis: {pad_rows}.</p>
<table>
<thead><tr>
<th class="text">Band</th><th class="text">Antenna</th><th>Baseline avg (dBm)</th><th>Loaded avg (dBm)</th>
<th>Delta (dB)</th><th>Baseline P90</th><th>Loaded P90</th>
<th>Avg limit</th><th>P90 limit</th><th>Delta limit</th><th class="text">Result</th>
</tr></thead>
<tbody>
{"".join(body_rows)}
</tbody>
</table>
{note_block}
<h2>Per-band charts</h2>
<div class="grid">
{"".join(images)}
</div>
</body>
</html>
"""


def write_summary(out_dir: Path, verdicts: list[Verdict], chart_paths: list[Path], pad_rows: int) -> tuple[Path, Path]:
    md_path = out_dir / "summary.md"
    html_path = out_dir / "summary.html"
    md_path.write_text(_markdown(verdicts, chart_paths, pad_rows), encoding="utf-8")
    html_path.write_text(_html(verdicts, chart_paths, pad_rows), encoding="utf-8")
    return md_path, html_path


def run(raw_dir: Path, limits_path: Path, out_dir: Path) -> None:
    converted = convert_directory(raw_dir, out_dir / "normalized")
    rows = read_normalized(converted.combined_path)
    verdicts, grouped = score(rows, load_limits(limits_path))
    charts = write_charts(out_dir / "charts", verdicts, grouped)
    summary_md, summary_html = write_summary(out_dir, verdicts, charts, converted.pad_rows)
    print(converted.summary())
    print(f"Wrote {summary_md}")
    print(f"Wrote {summary_html}")
    for verdict in verdicts:
        print(
            f"{verdict.mode} {verdict.band} {verdict.antenna}: {verdict.result} "
            f"avg {verdict.loaded_avg:.2f} dBm  delta {verdict.delta:.2f} dB"
        )


def main() -> None:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=root / "sample_data" / "raw")
    parser.add_argument(
        "--limits",
        type=Path,
        default=root / "sample_data" / "illustrative_limits.csv",
    )
    parser.add_argument("--output-dir", type=Path, default=root / "output")
    args = parser.parse_args()
    run(args.raw_dir, args.limits, args.output_dir)


if __name__ == "__main__":
    main()
