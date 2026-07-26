# Change Risk Sentry

Rust CLI that audits a local git worktree and turns the current diff surface into a short review-risk brief.

## Why this exists

Before a push or PR, it is easy to ask "what changed?" and still miss the more useful question: "what part of this change deserves extra review attention?" This tool answers that second question by classifying the touched files, surfacing churn hotspots, and flagging common risk patterns.

## What it checks

- Source vs test vs docs vs config vs lockfile footprint
- Staged and unstaged churn totals from `git diff --numstat`
- Top churn files in the current worktree
- Optional base-branch review mode so you can audit the full committed branch delta before opening a PR
- Review-risk signals such as:
  - source changes without tests
  - files with mixed staged and unstaged edits
  - large deletion-heavy edits
  - broad blast radius across top-level directories
  - config/deployment-facing edits
  - lockfile-only changes
  - untracked files that can be forgotten during commit prep

## Build

```bash
cargo build --release
```

## Run

Audit the current repo:

```bash
cargo run -- .
```

Audit the committed branch delta versus `origin/main`:

```bash
cargo run -- . --base origin/main
```

Audit another repo and write a markdown brief:

```bash
cargo run -- C:\path\to\repo --md-out artifacts\risk-report.md
```

Write both JSON and Markdown artifacts:

```bash
cargo run -- . --json-out artifacts\risk-report.json --md-out artifacts\risk-report.md
```

Fail a CI step when medium-or-higher review risk is detected:

```bash
cargo run -- . --fail-on medium
```

## Example output

```text
Change Risk Sentry
Repo: C:\repo
Branch: main
Mode: Worktree risk review
Headline: Moderate review attention recommended
Files touched: 6
```

The full console output also includes a category breakdown, top churn files, and risk flags.

## CI-friendly gating

If you pass `--fail-on low|medium|high`, the tool still prints and writes the normal report, then exits non-zero when the highest detected risk level meets or exceeds that threshold.

This is useful for:

- pre-push hooks
- GitHub Actions review guardrails
- local "pause before merge" workflows

## Portfolio Positioning

- Project type: Rust CLI utility
- Verification path: `cargo run -- .` inside any git repo with pending changes
