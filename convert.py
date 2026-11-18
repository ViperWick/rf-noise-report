#!/usr/bin/env python3
"""Format bridge for synthetic RX noise-power logs.

The instrument export is a wide CSV: 1-based RX0001..RX0100 sample columns,
loose Mode/Band labels, and one row per antenna. This stage writes the fixed
column contract the report consumes:

- Mode becomes LTE or NR; Band becomes B3 / B7 / B12 / n78 style labels
- RX0001..RX0100 are renamed in place to RX0000..RX0099
- Missing channel/antenna rows are inserted so every series shares one x-axis
- The text file uses CRLF line endings
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, field
from pathlib import Path


N_SAMPLES = 100

RAW_LEADING = [
    "Time",
    "Mode",
    "Band",
    "BW",
    "Channel",
    "Frequency",
    "StartRB",
    "NumRB",
    "TARGET_TX_PWR",
    "RxId",
]
RAW_RX_COLUMNS = [f"RX{i:04d}" for i in range(1, N_SAMPLES + 1)]
AGC_COLUMNS = ["RxAGC_Mean", "RxAGC_95thPercentile", "RxAGC_Max"]
RAW_COLUMNS = RAW_LEADING + RAW_RX_COLUMNS + AGC_COLUMNS

NORM_LEADING = [
    "Time",
    "Config",
    "Mode",
    "Band",
    "BW",
    "Channel",
    "Frequency",
    "StartRB",
    "NumRB",
    "TARGET_TX_PWR",
    "RxId",
    "Antenna",
    "AxisIndex",
    "RowKind",
]
NORM_RX_COLUMNS = [f"RX{i:04d}" for i in range(0, N_SAMPLES)]
NORMALIZED_COLUMNS = NORM_LEADING + NORM_RX_COLUMNS + AGC_COLUMNS

BAND_ORDER = ["B3", "B7", "B12", "n78"]
CONFIG_ORDER = ["Baseline", "Loaded"]


@dataclass
class ConvertResult:
    combined_path: Path
    band_paths: dict[str, Path]
    measurement_rows: int
    pad_rows: int
    mode_labels: dict[str, str] = field(default_factory=dict)
    band_labels: dict[str, str] = field(default_factory=dict)

    def summary(self) -> str:
        lines = [
            f"Measurements: {self.measurement_rows}",
            f"Padded rows: {self.pad_rows}",
            "Mode labels:",
        ]
        for raw, norm in sorted(self.mode_labels.items()):
            lines.append(f"  {raw!r} -> {norm}")
        lines.append("Band labels:")
        for raw, norm in sorted(self.band_labels.items()):
            lines.append(f"  {raw!r} -> {norm}")
        lines.append(f"Wrote {self.combined_path} (CRLF)")
        for path in self.band_paths.values():
            lines.append(f"Wrote {path} (CRLF)")
        return "\n".join(lines)


def normalize_mode(value: str) -> str:
    text = " ".join(value.strip().lower().replace("_", " ").replace("-", " ").split())
    if "lte" in text:
        return "LTE"
    if "nr" in text or "5g" in text:
        return "NR"
    raise ValueError(f"Unrecognized mode label: {value!r}")


def normalize_band(value: str) -> str:
    text = value.strip().lower().replace("_", " ").replace("-", " ")
    text = text.replace("band", "")
    text = "".join(text.split())
    if text.startswith("n") and text[1:].isdigit():
        return "n" + str(int(text[1:]))
    if text.startswith("b") and text[1:].isdigit():
        return "B" + str(int(text[1:]))
    if text.isdigit():
        return "B" + str(int(text))
    raise ValueError(f"Unrecognized band label: {value!r}")


def antenna_name(rx_id: int) -> str:
    if rx_id == 0:
        return "main"
    if rx_id == 1:
        return "aux"
    raise ValueError(f"RxId must be 0 (main) or 1 (aux), got {rx_id}")


def config_from_filename(path: Path) -> str:
    stem = path.stem.lower()
    if "baseline" in stem and "loaded" in stem:
        raise ValueError(f"Filename must name one config, got {path.name}")
    if "baseline" in stem:
        return "Baseline"
    if "loaded" in stem:
        return "Loaded"
    raise ValueError(
        f"Filename must include Baseline or Loaded so the bridge can tag the unit: {path.name}"
    )


def _whole_number(text: str) -> str:
    number = float(text)
    if number.is_integer():
        return str(int(number))
    return f"{number:.4f}".rstrip("0").rstrip(".")


def _require_columns(path: Path, fieldnames: list[str] | None) -> None:
    missing = [name for name in RAW_COLUMNS if not fieldnames or name not in fieldnames]
    if missing:
        preview = ", ".join(missing[:6])
        extra = "" if len(missing) <= 6 else f" (+{len(missing) - 6} more)"
        raise ValueError(f"{path.name} is missing raw columns: {preview}{extra}")


def read_raw_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        _require_columns(path, reader.fieldnames)
        rows = []
        for line_no, row in enumerate(reader, start=2):
            cleaned = {key: (value or "").strip() for key, value in row.items() if key}
            cleaned["_line"] = str(line_no)
            rows.append(cleaned)
    return rows


def _measurement_from_raw(row: dict[str, str], config: str, source: str) -> dict[str, str]:
    raw_mode = row["Mode"]
    raw_band = row["Band"]
    mode = normalize_mode(raw_mode)
    band = normalize_band(raw_band)
    try:
        rx_id = int(float(row["RxId"]))
    except ValueError as exc:
        raise ValueError(f"{source}: RxId {row['RxId']!r} is not an integer") from exc
    samples = []
    for column in RAW_RX_COLUMNS:
        text = row[column]
        if text == "":
            raise ValueError(f"{source}: {column} is blank on a measurement row")
        samples.append(f"{float(text):.2f}")
    normalized = {
        "Time": row["Time"],
        "Config": config,
        "Mode": mode,
        "Band": band,
        "BW": _whole_number(row["BW"]),
        "Channel": _whole_number(row["Channel"]),
        "Frequency": f"{float(row['Frequency']):.1f}",
        "StartRB": _whole_number(row["StartRB"]),
        "NumRB": _whole_number(row["NumRB"]),
        "TARGET_TX_PWR": _whole_number(row["TARGET_TX_PWR"]),
        "RxId": str(rx_id),
        "Antenna": antenna_name(rx_id),
        "AxisIndex": "",
        "RowKind": "meas",
        "_raw_mode": raw_mode,
        "_raw_band": raw_band,
    }
    for index, column in enumerate(NORM_RX_COLUMNS):
        normalized[column] = samples[index]
    for column in AGC_COLUMNS:
        normalized[column] = f"{float(row[column]):.2f}"
    return normalized


def _band_sort_key(band: str) -> tuple[int, int | str]:
    if band in BAND_ORDER:
        return (0, BAND_ORDER.index(band))
    return (1, band)


def _write_crlf(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=NORMALIZED_COLUMNS,
            lineterminator="\r\n",
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in NORMALIZED_COLUMNS})
    _validate_crlf(path)


def _validate_crlf(path: Path) -> None:
    payload = path.read_bytes()
    if b"\r\n" not in payload:
        raise ValueError(f"{path} was not written with CRLF line endings")
    if b"\n" in payload.replace(b"\r\n", b""):
        raise ValueError(f"{path} mixes LF with CRLF")
    header = payload.split(b"\r\n", 1)[0].decode("utf-8")
    if header.split(",") != NORMALIZED_COLUMNS:
        raise ValueError(f"{path} header does not match the normalized column contract")


def convert_directory(raw_dir: Path, out_dir: Path) -> ConvertResult:
    files = sorted(path for path in raw_dir.glob("*.csv") if path.is_file())
    if not files:
        raise ValueError(f"No raw CSV files in {raw_dir}")

    measurements: list[dict[str, str]] = []
    mode_labels: dict[str, str] = {}
    band_labels: dict[str, str] = {}
    for path in files:
        config = config_from_filename(path)
        for row in read_raw_csv(path):
            source = f"{path.name}:{row['_line']}"
            normalized = _measurement_from_raw(row, config, source)
            mode_labels.setdefault(row["Mode"], normalized["Mode"])
            band_labels.setdefault(row["Band"], normalized["Band"])
            measurements.append(normalized)

    by_key: dict[tuple[str, str, str, str], dict[str, str]] = {}
    for row in measurements:
        key = (row["Config"], row["Band"], row["Channel"], row["RxId"])
        if key in by_key:
            raise ValueError(
                "Duplicate measurement for "
                f"config={key[0]} band={key[1]} channel={key[2]} RxId={key[3]}"
            )
        by_key[key] = row

    bands = sorted({row["Band"] for row in measurements}, key=_band_sort_key)
    aligned: list[dict[str, str]] = []
    pad_rows = 0
    for band in bands:
        points = [
            (float(row["Frequency"]), row["Channel"])
            for row in measurements
            if row["Band"] == band
        ]
        axis: list[tuple[float, str]] = []
        seen: dict[str, float] = {}
        for frequency, channel in sorted(points):
            prior = seen.get(channel)
            if prior is None:
                seen[channel] = frequency
                axis.append((frequency, channel))
            elif prior != frequency:
                raise ValueError(
                    f"Band {band} channel {channel} has frequencies {prior} and {frequency}"
                )
        donors = [row for row in measurements if row["Band"] == band]
        for axis_index, (frequency, channel) in enumerate(axis):
            for config in CONFIG_ORDER:
                if not any(row["Config"] == config for row in donors):
                    continue
                for rx_id in (0, 1):
                    key = (config, band, channel, str(rx_id))
                    current = by_key.get(key)
                    if current is None:
                        current = _pad_row(donors, config, band, channel, frequency, rx_id)
                        pad_rows += 1
                    current["AxisIndex"] = str(axis_index)
                    current["Frequency"] = f"{frequency:.1f}"
                    aligned.append(current)

    if not aligned:
        raise ValueError("Raw files contained no measurements")

    combined_path = out_dir / "rx_noise_normalized.csv"
    _write_crlf(combined_path, aligned)
    band_paths: dict[str, Path] = {}
    for band in bands:
        band_rows = [row for row in aligned if row["Band"] == band]
        band_path = out_dir / "by_band" / f"{band}.csv"
        _write_crlf(band_path, band_rows)
        band_paths[band] = band_path
        _check_axis_alignment(band, band_rows)

    return ConvertResult(
        combined_path=combined_path,
        band_paths=band_paths,
        measurement_rows=len(measurements),
        pad_rows=pad_rows,
        mode_labels=mode_labels,
        band_labels=band_labels,
    )


def _pad_row(
    donors: list[dict[str, str]],
    config: str,
    band: str,
    channel: str,
    frequency: float,
    rx_id: int,
) -> dict[str, str]:
    same_config = next(row for row in donors if row["Config"] == config)
    padded = {
        "Time": "",
        "Config": config,
        "Mode": same_config["Mode"],
        "Band": band,
        "BW": same_config["BW"],
        "Channel": channel,
        "Frequency": f"{frequency:.1f}",
        "StartRB": same_config["StartRB"],
        "NumRB": same_config["NumRB"],
        "TARGET_TX_PWR": same_config["TARGET_TX_PWR"],
        "RxId": str(rx_id),
        "Antenna": antenna_name(rx_id),
        "AxisIndex": "",
        "RowKind": "pad",
    }
    for column in NORM_RX_COLUMNS + AGC_COLUMNS:
        padded[column] = ""
    return padded


def _check_axis_alignment(band: str, rows: list[dict[str, str]]) -> None:
    counts: dict[tuple[str, str], int] = {}
    for row in rows:
        key = (row["Config"], row["Antenna"])
        counts[key] = counts.get(key, 0) + 1
    lengths = set(counts.values())
    if len(lengths) != 1:
        raise ValueError(f"Band {band} series do not share one channel axis: {counts}")


def read_normalized(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != NORMALIZED_COLUMNS:
            raise ValueError(f"{path} header does not match the normalized column contract")
        return list(reader)


def main() -> None:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=root / "sample_data" / "raw")
    parser.add_argument("--output-dir", type=Path, default=root / "output" / "normalized")
    args = parser.parse_args()
    result = convert_directory(args.raw_dir, args.output_dir)
    print(result.summary())


if __name__ == "__main__":
    main()
