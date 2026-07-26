# Bookmark Health Brief

Python CLI for auditing Chrome or Edge bookmark exports before duplicate links, dead folders, and risky URL schemes turn the collection into clutter.

## What it checks

- duplicate bookmark URLs
- duplicate bookmark titles
- risky URL schemes such as `http`, `file`, `javascript`, or browser-internal links
- empty folders that should probably be deleted or repopulated
- deep folder chains that make bookmarks hard to rediscover
- optional HTTP/HTTPS reachability checks for broken web links

## Why it is useful

Bookmarks accumulate quietly. After enough imports, browser switches, and quick saves, the collection stops acting like a retrieval tool and starts acting like a junk drawer. This CLI turns that sprawl into one cleanup brief.

## Usage

Run against the sample export:

```bash
python bookmark_health_brief.py --input samples/sample-bookmarks.json
```

Write JSON and Markdown reports:

```bash
python bookmark_health_brief.py ^
  --input samples/sample-bookmarks.json ^
  --json-out reports/sample-report.json ^
  --markdown-out reports/sample-report.md
```

Optionally check live URLs:

```bash
python bookmark_health_brief.py --input bookmarks.json --check-urls --timeout 3
```

## Verification

```bash
python bookmark_health_brief.py --input samples/sample-bookmarks.json --json-out reports/self-check.json --markdown-out reports/self-check.md
```

## Portfolio positioning

- Project type: Python CLI workflow utility
- Target workflow: browser bookmark cleanup and migration review
- Direction fit: practical non-browser software for a real personal workflow
