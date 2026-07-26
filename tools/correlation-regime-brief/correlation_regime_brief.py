from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Observation:
    date: str
    values: dict[str, float | None]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a rolling-correlation brief around one anchor asset.")
    parser.add_argument("--input", type=Path, required=True, help="Wide CSV with one date column and return columns.")
    parser.add_argument("--anchor", required=True, help="Ticker/series name to compare against all other columns.")
    parser.add_argument("--window", type=int, default=20, help="Rolling observation count per pair.")
    parser.add_argument(
        "--pair-threshold",
        type=float,
        default=0.65,
        help="Absolute rolling-correlation threshold worth flagging.",
    )
    parser.add_argument("--markdown-out", type=Path, help="Optional Markdown brief path.")
    parser.add_argument("--json-out", type=Path, help="Optional JSON summary path.")
    return parser.parse_args()


def parse_return(raw: str, field_name: str, row_number: int) -> float | None:
    cleaned = raw.strip()
    if cleaned == "":
        return None
    try:
        if cleaned.endswith("%"):
            return float(cleaned[:-1]) / 100.0
        return float(cleaned)
    except ValueError as exc:
        raise ValueError(f"Invalid return value for {field_name} at row {row_number}.") from exc


def load_observations(path: Path) -> tuple[str, list[str], list[Observation]]:
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        if len(fieldnames) < 3:
            raise ValueError("Input CSV must include one date column and at least two asset columns.")

        date_field = fieldnames[0]
        assets = [field.strip().upper() for field in fieldnames[1:] if field.strip()]
        observations: list[Observation] = []

        for row_number, row in enumerate(reader, start=2):
            date_value = str(row.get(date_field, "")).strip()
            if not date_value:
                raise ValueError(f"Missing date at row {row_number}.")

            values = {
                asset: parse_return(str(row.get(asset, "")), asset, row_number)
                for asset in assets
            }
            observations.append(Observation(date=date_value, values=values))

    if not observations:
        raise ValueError("Input CSV is empty.")
    return date_field, assets, observations


def pearson(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        raise ValueError("Need at least two aligned observations to compute correlation.")

    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    covariance = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    left_var = sum((a - left_mean) ** 2 for a in left)
    right_var = sum((b - right_mean) ** 2 for b in right)
    denominator = math.sqrt(left_var * right_var)
    if denominator == 0:
        return 0.0
    return max(-1.0, min(1.0, covariance / denominator))


def build_pair_series(
    observations: list[Observation],
    anchor: str,
    asset: str,
    window: int,
) -> list[dict[str, float | str]]:
    aligned: list[tuple[str, float, float]] = []
    series: list[dict[str, float | str]] = []

    for observation in observations:
        anchor_value = observation.values.get(anchor)
        asset_value = observation.values.get(asset)
        if anchor_value is None or asset_value is None:
            continue

        aligned.append((observation.date, anchor_value, asset_value))
        if len(aligned) < window:
            continue

        window_slice = aligned[-window:]
        left = [entry[1] for entry in window_slice]
        right = [entry[2] for entry in window_slice]
        series.append(
            {
                "date": observation.date,
                "correlation": round(pearson(left, right), 4),
            }
        )

    return series


def classify_regime(latest: float, average_abs: float, sign_flips: int, threshold: float) -> str:
    latest_abs = abs(latest)
    if latest_abs >= threshold and latest > 0:
        return "high-coupling"
    if latest_abs >= threshold and latest < 0:
        return "strong-hedge"
    if sign_flips >= 3 and average_abs >= threshold / 2:
        return "unstable-drift"
    if average_abs < threshold / 2:
        return "diversifying"
    return "mixed"


def summarize_pair(asset: str, series: list[dict[str, float | str]], threshold: float) -> dict[str, float | int | str]:
    correlations = [float(point["correlation"]) for point in series]
    latest = correlations[-1]
    sign_flips = sum(
        1
        for previous, current in zip(correlations, correlations[1:])
        if previous != 0 and current != 0 and ((previous < 0 < current) or (previous > 0 > current))
    )
    threshold_breaches = sum(1 for value in correlations if abs(value) >= threshold)
    average_abs = sum(abs(value) for value in correlations) / len(correlations)

    return {
        "asset": asset,
        "latest_correlation": round(latest, 4),
        "min_correlation": round(min(correlations), 4),
        "max_correlation": round(max(correlations), 4),
        "average_abs_correlation": round(average_abs, 4),
        "sign_flips": sign_flips,
        "threshold_breaches": threshold_breaches,
        "series_points": len(correlations),
        "latest_date": str(series[-1]["date"]),
        "regime": classify_regime(latest, average_abs, sign_flips, threshold),
    }


def build_report(
    observations: list[Observation],
    assets: list[str],
    anchor: str,
    window: int,
    threshold: float,
) -> dict[str, object]:
    summaries: list[dict[str, float | int | str]] = []
    series_by_asset: dict[str, list[dict[str, float | str]]] = {}

    for asset in assets:
        if asset == anchor:
            continue
        series = build_pair_series(observations, anchor, asset, window)
        if not series:
            continue
        series_by_asset[asset] = series
        summaries.append(summarize_pair(asset, series, threshold))

    if not summaries:
        raise ValueError("No pair had enough aligned observations for the requested rolling window.")

    summaries.sort(key=lambda item: abs(float(item["latest_correlation"])), reverse=True)
    most_diversifying = min(
        summaries,
        key=lambda item: (float(item["average_abs_correlation"]), abs(float(item["latest_correlation"]))),
    )
    most_coupled = max(summaries, key=lambda item: abs(float(item["latest_correlation"])))

    return {
        "anchor": anchor,
        "window": window,
        "pair_threshold": threshold,
        "observation_count": len(observations),
        "pairs_analyzed": len(summaries),
        "latest_date": summaries[0]["latest_date"],
        "most_diversifying_pair": most_diversifying["asset"],
        "most_coupled_pair": most_coupled["asset"],
        "pair_summaries": summaries,
        "series_by_asset": series_by_asset,
    }


def print_report(report: dict[str, object]) -> None:
    print("Correlation Regime Brief")
    print("========================")
    print(f"Anchor asset:            {report['anchor']}")
    print(f"Rolling window:          {report['window']} observations")
    print(f"Pairs analyzed:          {report['pairs_analyzed']}")
    print(f"Latest sampled date:     {report['latest_date']}")
    print(f"Threshold watch:         {float(report['pair_threshold']):.2f}")
    print(f"Most coupled pair:       {report['anchor']} vs {report['most_coupled_pair']}")
    print(f"Most diversifying pair:  {report['anchor']} vs {report['most_diversifying_pair']}")
    print()
    print(
        f"{'Pair':<16} {'Latest':>8} {'Min':>8} {'Max':>8} {'Avg |corr|':>11} "
        f"{'Flips':>7} {'Breaches':>9} {'Regime':>15}"
    )
    print("-" * 90)
    for row in report["pair_summaries"]:
        print(
            f"{report['anchor']} vs {row['asset']:<7} "
            f"{float(row['latest_correlation']):>8.4f} "
            f"{float(row['min_correlation']):>8.4f} "
            f"{float(row['max_correlation']):>8.4f} "
            f"{float(row['average_abs_correlation']):>11.4f} "
            f"{int(row['sign_flips']):>7} "
            f"{int(row['threshold_breaches']):>9} "
            f"{str(row['regime']):>15}"
        )


def build_markdown(report: dict[str, object]) -> str:
    lines = [
        "# Correlation Regime Brief",
        "",
        f"- Anchor asset: `{report['anchor']}`",
        f"- Rolling window: `{report['window']}` observations",
        f"- Latest sampled date: `{report['latest_date']}`",
        f"- Pair threshold: `{float(report['pair_threshold']):.2f}`",
        f"- Most coupled pair: `{report['anchor']} vs {report['most_coupled_pair']}`",
        f"- Most diversifying pair: `{report['anchor']} vs {report['most_diversifying_pair']}`",
        "",
        "## Pair summary",
        "",
        "| Pair | Latest | Min | Max | Avg abs corr | Flips | Breaches | Regime |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in report["pair_summaries"]:
        lines.append(
            f"| {report['anchor']} vs {row['asset']} | {float(row['latest_correlation']):.4f} | "
            f"{float(row['min_correlation']):.4f} | {float(row['max_correlation']):.4f} | "
            f"{float(row['average_abs_correlation']):.4f} | {int(row['sign_flips'])} | "
            f"{int(row['threshold_breaches'])} | {row['regime']} |"
        )
    return "\n".join(lines) + "\n"


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> None:
    args = parse_args()
    _, assets, observations = load_observations(args.input)
    anchor = args.anchor.strip().upper()
    if anchor not in assets:
        raise ValueError(f"Anchor asset '{anchor}' is not present in the CSV columns.")
    if args.window < 2:
        raise ValueError("window must be at least 2.")
    if not 0 <= args.pair_threshold <= 1:
        raise ValueError("pair-threshold must be between 0 and 1.")

    report = build_report(observations, assets, anchor, args.window, args.pair_threshold)
    print_report(report)

    if args.markdown_out:
        write_text(args.markdown_out, build_markdown(report))
        print(f"\nWrote Markdown brief: {args.markdown_out}")

    if args.json_out:
        write_text(args.json_out, json.dumps(report, indent=2))
        print(f"Wrote JSON summary: {args.json_out}")


if __name__ == "__main__":
    main()
