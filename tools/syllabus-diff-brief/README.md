# Syllabus Diff Brief

Rust CLI for comparing two syllabus text exports and turning the differences into one concise review brief.

## Why It Exists

Course syllabi get revised after the semester starts, but the changes are usually buried inside long documents. This tool compares two plain-text or markdown syllabus exports and flags the lines most likely to matter first: grading, exams, attendance, late work, dates, and course-policy changes.

## Features

- Compares two syllabus exports with whitespace-tolerant normalization.
- Collapses near-match policy edits into one modified-line report instead of making you mentally pair a removed line with a reworded replacement.
- Buckets changes into grading, exams, attendance, late work, schedule, materials, contact, or general updates.
- Assigns a simple priority score so grading and date changes float to the top.
- Adds an immediate-check section so the highest-risk grading, exam, and date edits surface before the full diff.
- Prints a markdown brief to stdout.
- Optionally writes markdown and JSON artifacts for archiving or follow-up.
- Ships with unit tests for normalization, categorization, and diff behavior.

## Usage

```bash
cargo run -- syllabus_v1.txt syllabus_v2.txt
```

Write reusable artifacts:

```bash
cargo run -- syllabus_v1.txt syllabus_v2.txt --markdown report.md --json report.json
```

## Input Expectations

- Use plain text or markdown exports.
- Blank lines and list-marker noise are normalized away.
- PDF text should be extracted first before running the tool.

## Verification

```bash
cargo test
cargo run -- --help
```

## Stack

- Rust
- Standard library only
