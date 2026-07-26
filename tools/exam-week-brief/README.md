# Exam Week Brief

Rust CLI that turns an exam schedule CSV into one concise week-ahead brief: conflict watch, same-day turnaround risk, daily exam load, prep-hour backplan, and a focus order.

## Why It Exists

Finals week gets messy fast when multiple exams land on the same day and prep hours pile onto the same few nights. This tool gives a fast planning pass before the week starts so you can spot collisions and overloaded prep days early.

## Input CSV

```csv
course,exam_date,start_time,end_time,location,prep_hours
CS 3345,2026-12-14,09:00,11:00,ECSS 2.102,6
```

- `exam_date` uses `YYYY-MM-DD`
- `start_time` and `end_time` use 24-hour `HH:MM`
- `prep_hours` is optional and defaults to `4`

## Usage

Print the brief to stdout:

```bash
cargo run -- --input sample_exams.csv
```

Write reusable artifacts:

```bash
cargo run -- --input sample_exams.csv --markdown reports/brief.md --json reports/brief.json
```

Tune the planning assumptions:

```bash
cargo run -- --input sample_exams.csv --prep-window-days 4 --daily-cap 3.0 --today 2026-12-10
```

Skip work-shift or travel days when backplanning prep:

```bash
cargo run -- --input sample_exams.csv --today 2026-12-10 --blocked-date 2026-12-12 --blocked-date 2026-12-13
```

Skip recurring weekdays too:

```bash
cargo run -- --input sample_exams.csv --today 2026-12-11 --blocked-weekday sat --blocked-weekday sun
```

## Output

- Overlapping exam detection
- Same-day turnaround warnings under 90 minutes
- Day-by-day exam load summary
- Backplanned prep hours spread across the days leading into each exam
- Blocked-date aware prep planning with gap warnings when no valid prep day remains
- Optional blocked weekdays so weekend-only or workday-only study plans stay realistic
- Overloaded prep-day flags when the estimated hours exceed the cap
- Focus order ranked by time-to-exam and prep intensity

## Verification

```bash
cargo test
cargo run -- --input sample_exams.csv --today 2026-12-10
```

## Stack

- Rust
- `chrono`
- `csv`
- `serde`
- `serde_json`
