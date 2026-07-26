# Log Window Extractor

Python CLI that carves a focused incident window out of one or more raw log files.

## Why it exists

During debugging, teams often have the rough minute an incident started but still waste time scrolling through full logs. This tool trims the search space to a precise before/after window, keeps only timestamped lines, and produces artifacts that are easier to hand to another engineer.

## What it does

- accepts one or more plaintext log files
- filters by explicit start/end or by an anchor timestamp plus before/after minutes
- optionally narrows the results with a case-insensitive regex
- exports the matching lines, a Markdown brief, and a JSON summary
- counts alert-like keywords such as `error`, `warn`, `timeout`, `exception`, and `retry`
- sorts matches chronologically across multiple files and surfaces the largest quiet gaps inside the window

## Usage

Filter around an anchor event:

```bash
python log_window_extractor.py sample_logs/incident.log --anchor 2026-07-01T14:05:00Z --before-minutes 8 --after-minutes 10 --out reports/window.log --summary-out reports/window.md --json-out reports/window.json
```

Use a fixed absolute window and only keep timeout lines:

```bash
python log_window_extractor.py sample_logs/incident.log --start 2026-07-01T14:00:00Z --end 2026-07-01T14:12:00Z --match timeout
```

Combine several rotated logs and inspect the biggest pauses inside the incident slice:

```bash
python log_window_extractor.py sample_logs/*.log --anchor 2026-07-01T14:05:00Z --before-minutes 8 --after-minutes 10 --summary-out reports/window.md --json-out reports/window.json
```

## Verification

```bash
python -m unittest
python log_window_extractor.py sample_logs/incident.log --anchor 2026-07-01T14:05:00Z --before-minutes 8 --after-minutes 10 --summary-out reports/window.md --json-out reports/window.json
```

## Portfolio positioning

- Project type: Python command-line incident workflow utility
- Strongest use: isolate the meaningful log slice around a deploy, alert, or outage start
