# Calendar Conflict Scout

Rust CLI that scans one or more `.ics` calendars for overlaps, tight turnarounds, and the best free windows inside a study or workday.

## Why It Exists

Calendar exports are easy to generate and annoying to compare. This tool turns multiple ICS files into one conflict brief you can actually act on before classes, meetings, or deadlines collide.

## What It Does

- Reads one or more `.ics` files.
- Filters events to a requested date range.
- Detects overlapping events across the combined schedule.
- Flags tight turnarounds under a configurable minute threshold.
- Computes free windows between `day-start` and `day-end`.
- Adds a day-level load summary so overloaded dates stand out before you inspect each event.
- Exports the full report as Markdown and/or JSON.

## Usage

```bash
cargo run -- \
  --input fall-classes.ics \
  --input personal.ics \
  --start 2026-07-01 \
  --end 2026-07-03 \
  --day-start 08:00 \
  --day-end 21:00 \
  --min-gap-minutes 45 \
  --markdown-out artifacts/report.md \
  --json-out artifacts/report.json
```

## Example Console Output

```text
Calendar Conflict Scout | 2026-07-01 to 2026-07-03
Calendars: 2 | Events: 14 | Conflicts: 2 | Tight turnarounds: 3 | Free windows: 11
```

## Notes

- Supports common ICS `DTSTART`, `DTEND`, `SUMMARY`, and `LOCATION` fields.
- Handles floating local times, UTC `Z` timestamps, and all-day events.
- This version does not evaluate full `VTIMEZONE` rule sets; it uses the clock values written in the files.

## Verification

```bash
cargo test
cargo run -- --help
```
