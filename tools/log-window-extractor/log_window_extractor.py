from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

TIMESTAMP_PATTERN = re.compile(
    r"(?P<stamp>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)"
)
KEYWORDS = ("error", "warn", "timeout", "exception", "retry")


@dataclass
class LogMatch:
    source: str
    line_number: int
    timestamp: datetime
    line: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract time-bounded log windows around an incident.")
    parser.add_argument("inputs", nargs="+", type=Path, help="One or more log files to scan.")
    parser.add_argument("--start", help="Window start as ISO timestamp.")
    parser.add_argument("--end", help="Window end as ISO timestamp.")
    parser.add_argument("--anchor", help="Anchor ISO timestamp. Use with --before-minutes/--after-minutes.")
    parser.add_argument("--before-minutes", type=int, default=10, help="Minutes before anchor to include.")
    parser.add_argument("--after-minutes", type=int, default=15, help="Minutes after anchor to include.")
    parser.add_argument("--match", help="Optional case-insensitive regex that filtered lines must also satisfy.")
    parser.add_argument("--out", type=Path, help="Optional output path for the filtered log lines.")
    parser.add_argument("--summary-out", type=Path, help="Optional markdown summary path.")
    parser.add_argument("--json-out", type=Path, help="Optional JSON summary path.")
    return parser.parse_args()


def parse_iso_timestamp(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    if "T" not in normalized and " " in normalized:
        normalized = normalized.replace(" ", "T", 1)
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def resolve_window(args: argparse.Namespace) -> tuple[datetime, datetime]:
    if args.start or args.end:
        if not (args.start and args.end):
            raise ValueError("--start and --end must be provided together.")
        start = parse_iso_timestamp(args.start)
        end = parse_iso_timestamp(args.end)
    elif args.anchor:
        anchor = parse_iso_timestamp(args.anchor)
        start = anchor - timedelta(minutes=args.before_minutes)
        end = anchor + timedelta(minutes=args.after_minutes)
    else:
        raise ValueError("Provide either --start/--end or --anchor.")

    if end < start:
        raise ValueError("Window end must be at or after the start.")
    return start, end


def extract_timestamp(line: str) -> datetime | None:
    match = TIMESTAMP_PATTERN.search(line)
    if not match:
        return None
    try:
        return parse_iso_timestamp(match.group("stamp"))
    except ValueError:
        return None


def collect_matches(
    paths: list[Path],
    start: datetime,
    end: datetime,
    pattern: re.Pattern[str] | None = None,
) -> list[LogMatch]:
    matches: list[LogMatch] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for line_number, raw_line in enumerate(text.splitlines(), start=1):
            timestamp = extract_timestamp(raw_line)
            if timestamp is None or timestamp < start or timestamp > end:
                continue
            if pattern and not pattern.search(raw_line):
                continue
            matches.append(
                LogMatch(
                    source=path.name,
                    line_number=line_number,
                    timestamp=timestamp,
                    line=raw_line,
                )
            )
    matches.sort(key=lambda match: (match.timestamp, match.source, match.line_number))
    return matches


def build_timeline_gaps(matches: list[LogMatch]) -> list[dict[str, object]]:
    gaps: list[dict[str, object]] = []
    for previous, current in zip(matches, matches[1:]):
        gap_seconds = int((current.timestamp - previous.timestamp).total_seconds())
        if gap_seconds <= 0:
            continue
        gaps.append(
            {
                "gap_seconds": gap_seconds,
                "from": previous.timestamp.isoformat(),
                "to": current.timestamp.isoformat(),
                "from_source": previous.source,
                "to_source": current.source,
            }
        )
    return sorted(gaps, key=lambda gap: int(gap["gap_seconds"]), reverse=True)


def summarize(matches: list[LogMatch], start: datetime, end: datetime) -> dict[str, object]:
    per_file = Counter(match.source for match in matches)
    keyword_counts = Counter()
    for match in matches:
        lowered = match.line.lower()
        for keyword in KEYWORDS:
            if keyword in lowered:
                keyword_counts[keyword] += 1
    timeline_gaps = build_timeline_gaps(matches)

    return {
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "match_count": len(matches),
        "files_touched": dict(sorted(per_file.items())),
        "keyword_counts": dict(sorted(keyword_counts.items())),
        "first_match": matches[0].timestamp.isoformat() if matches else "",
        "last_match": matches[-1].timestamp.isoformat() if matches else "",
        "largest_gap_seconds": int(timeline_gaps[0]["gap_seconds"]) if timeline_gaps else 0,
        "timeline_gaps": timeline_gaps[:3],
    }


def build_markdown(summary: dict[str, object], matches: list[LogMatch]) -> str:
    lines = [
        "# Log Window Extract",
        "",
        f"- Window: `{summary['window_start']}` -> `{summary['window_end']}`",
        f"- Matched lines: {summary['match_count']}",
        f"- First match: `{summary['first_match'] or 'n/a'}`",
        f"- Last match: `{summary['last_match'] or 'n/a'}`",
        "",
        "## Files",
    ]

    files_touched = summary["files_touched"]
    if isinstance(files_touched, dict) and files_touched:
        for name, count in files_touched.items():
            lines.append(f"- `{name}`: {count} line(s)")
    else:
        lines.append("- No lines matched the requested window.")

    lines.extend(["", "## Keyword Counts"])
    keyword_counts = summary["keyword_counts"]
    if isinstance(keyword_counts, dict) and keyword_counts:
        for keyword, count in keyword_counts.items():
            lines.append(f"- `{keyword}`: {count}")
    else:
        lines.append("- No tracked alert keywords appeared in the filtered lines.")

    lines.extend(["", "## Timeline Gaps"])
    timeline_gaps = summary["timeline_gaps"]
    if isinstance(timeline_gaps, list) and timeline_gaps:
        for gap in timeline_gaps:
            lines.append(
                f"- `{int(gap['gap_seconds'])}s` gap from `{gap['from']}` to `{gap['to']}` "
                f"(`{gap['from_source']}` -> `{gap['to_source']}`)"
            )
    else:
        lines.append("- No meaningful gaps inside the filtered incident window.")

    lines.extend(["", "## Sample Lines"])
    for match in matches[:8]:
        lines.append(f"- `{match.source}:{match.line_number}` {match.line}")
    if not matches:
        lines.append("- No matching lines.")
    return "\n".join(lines) + "\n"


def build_output_lines(matches: list[LogMatch]) -> str:
    return "\n".join(
        f"{match.timestamp.isoformat()} [{match.source}:{match.line_number}] {match.line}"
        for match in matches
    ) + ("\n" if matches else "")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> None:
    args = parse_args()
    start, end = resolve_window(args)
    pattern = re.compile(args.match, re.IGNORECASE) if args.match else None
    matches = collect_matches(args.inputs, start, end, pattern)
    summary = summarize(matches, start, end)

    print("Log Window Extractor")
    print(f"Window: {summary['window_start']} -> {summary['window_end']}")
    print(f"Matched lines: {summary['match_count']}")
    print(f"Largest gap: {summary['largest_gap_seconds']}s")
    for name, count in summary["files_touched"].items():
        print(f"- {name}: {count} line(s)")

    if args.out:
        write_text(args.out, build_output_lines(matches))
        print(f"Wrote filtered log: {args.out}")
    if args.summary_out:
        write_text(args.summary_out, build_markdown(summary, matches))
        print(f"Wrote markdown summary: {args.summary_out}")
    if args.json_out:
        write_text(args.json_out, json.dumps(summary, indent=2))
        print(f"Wrote JSON summary: {args.json_out}")


if __name__ == "__main__":
    main()
