# Portfolio Utility Suite

One consolidated repo for the small practical CLI utilities that used to live as many separate portfolio repos.

The point of this repo is focus: improve installability, shared testing, shared documentation, and real workflows here instead of creating more tiny one-off projects.

## Tool Catalog

| Tool | Stack | Purpose |
| --- | --- | --- |
| `bookmark-health-brief` | Python | Audit browser bookmark exports for duplicates, risky schemes, empty folders, and optional broken-link checks. |
| `build-failure-brief` | Python | Turn noisy compiler and test logs into grouped failure summaries. |
| `calendar-conflict-scout` | Rust | Scan `.ics` calendars for overlaps, tight turnarounds, and free windows. |
| `change-risk-sentry` | Rust | Inspect local git diffs for review-risk signals. |
| `citation-gap-auditor` | Python | Find citation gaps in markdown research notes. |
| `correlation-regime-brief` | Python | Summarize rolling-correlation regime changes from return CSVs. |
| `course-grade-allocator` | Python | Calculate needed scores on remaining course components. |
| `dataset-split-auditor` | Java | Check ML dataset splits for leakage, duplicate IDs, temporal overlap, and label skew. |
| `deadline-calendar-builder` | Node.js | Convert deadline CSVs into calendar and planning artifacts. |
| `drawdown-window-analyzer` | C++ | Analyze equity-curve drawdowns and recovery windows. |
| `exam-week-brief` | Rust | Build an exam-week planning brief from schedule CSVs. |
| `focus-window-audit` | C# / .NET | Sample active Windows foreground windows into a focus report. |
| `folder-triage-cli` | C++ | Rank stale, large, and duplicate-looking files in a directory tree. |
| `listener-surface-auditor` | Go | Audit local TCP listeners on Windows. |
| `log-window-extractor` | Python | Extract focused incident windows from raw logs. |
| `options-payoff-grid` | Python | Sample multi-leg options payoff across an expiry price range. |
| `path-shadow-auditor` | PowerShell | Inspect Windows PATH ordering and command shadowing. |
| `pdf-annotation-digest` | Python | Extract PDF annotations into Markdown and JSON reading briefs. |
| `semester-workload-planner` | Python | Turn semester tasks into a day-by-day work plan. |
| `shell-history-risk-auditor` | Rust | Scan shell history for risky command habits. |
| `shortcut-target-auditor` | PowerShell | Audit Windows shortcut targets, duplicates, startup entries, and network-backed links. |
| `syllabus-diff-brief` | Rust | Compare syllabus exports and summarize grading or policy changes. |
| `trace-budget-auditor` | Python | Audit request traces against latency and error budgets. |
| `trade-journal-normalizer` | Python | Normalize broker CSV exports into a consistent trade journal. |
| `vault-link-auditor` | Python | Audit Obsidian-style vault links, duplicate note names, and orphan pages. |
| `wifi-profile-auditor` | Rust | Audit saved Windows Wi-Fi profiles. |
| `windows-autostart-auditor` | C# / .NET | Inspect Windows autostart surfaces. |
| `workspace-branch-watch` | C++ | Scan multi-repo workspaces for dirty worktrees and upstream drift. |
| `zip-risk-auditor` | Rust | Inspect zip archives for extraction hazards before opening them. |

## Layout

- `tools/<tool-name>/`: original tool source, README, and samples.
- `tool-manifest.json`: machine-readable catalog for future launchers, docs, and CI.
- `docs/autopilot-prompt.md`: replacement automation prompt focused on extended work.

## Near-Term Consolidation Plan

1. Add a shared `scripts/check.ps1` that runs syntax and smoke checks per stack.
2. Add a root launcher that can list tools and delegate to each tool's native entrypoint.
3. Normalize README sections so each utility has the same install, run, sample data, and verification shape.
4. Add CI for the tools that can run without Windows-only APIs.
5. Decide which older standalone repos should stay archived publicly and which should redirect here.

## Portfolio Positioning

This repo should be the visible portfolio surface for small CLI utilities. Individual tools can still be useful internally, but the public story should be a maintained suite instead of a long row of tiny project cards.
