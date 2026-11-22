# Portfolio Utility Suite

One consolidated repo for the small practical CLI utilities that used to live as many separate portfolio repos.

The point of this repo is focus: improve installability, shared testing, shared documentation, and real workflows here instead of creating more tiny one-off projects.

## Packet and waveform tools

Two self-contained tools have their own setup, tests, examples, and limitations:

- [StallWitness](tools/stallwitness): check saved ready/valid waveforms, find short failure witnesses, and compare accepted transactions across RTL runs. Includes a real SystemVerilog FIFO and seeded Icarus fault-injection evaluation.
- [RuleSplit](tools/rulesplit): compile an ordered IPv4 policy into a bounded prefix-table split, check decision equivalence, and replay synthetic PCAPs through Python and compiled C classifiers.

These run locally without API keys or device access. The packet-tools workflow checks their full documented paths on Linux; neither project claims physical silicon or DPU testing.

## Tool Catalog

| Tool | Stack | Purpose |
| --- | --- | --- |
| `stallwitness` | Python, SystemVerilog | Extract ready/valid failure witnesses and compare RTL transaction traces. |
| `rulesplit` | Python, C | Check an ordered ACL's CPU/offload split using exact packet-space coverage and PCAP replay. |
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
- `tool-manifest.json`: machine-readable catalog with stack, platform, entrypoint, and safe smoke-check metadata.
- `suite.ps1`: root launcher for listing, inspecting, running, and checking tools.
- `scripts/check.ps1`: shared verification entrypoint across the suite.
- `docs/autopilot-prompt.md`: replacement automation prompt focused on extended work.

## Root Workflow

List the suite catalog:

```powershell
powershell -ExecutionPolicy Bypass -File .\suite.ps1 -Action list
```

Show one tool's metadata:

```powershell
powershell -ExecutionPolicy Bypass -File .\suite.ps1 -Action info -Tool trace-budget-auditor
```

Run a tool through the shared launcher:

```powershell
powershell -ExecutionPolicy Bypass -File .\suite.ps1 -Action run -Tool trace-budget-auditor -ArgumentLine '--input sample_traces.csv'
```

Check the whole suite or one tool:

```powershell
python -m pip install --requirement .\requirements.txt
powershell -ExecutionPolicy Bypass -File .\suite.ps1 -Action check
powershell -ExecutionPolicy Bypass -File .\suite.ps1 -Action check -Tool deadline-calendar-builder
```

Compilation checks catch syntax and build failures. Runtime smoke checks go further by executing every tool against a bundled fixture, a safe local read-only workflow, or its CLI usage contract:

```powershell
powershell -ExecutionPolicy Bypass -File .\suite.ps1 -Action check -CheckMode smoke
powershell -ExecutionPolicy Bypass -File .\suite.ps1 -Action check -CheckMode smoke -Tool syllabus-diff-brief
```

Smoke commands are declared as argument arrays in `tool-manifest.json`; the checker always dispatches them through the same stack-aware runner used by `suite.ps1 -Action run`. This keeps verification aligned with the actual user path and avoids shell-evaluated command strings. Windows-only checks are identified in the manifest and skipped on unsupported hosts.

Product platform support and smoke-test platform support are tracked separately. A Windows utility can therefore keep honest runtime labeling while a deterministic capture or demo exercises its analysis path on Linux CI. Checks can also be narrowed to the same stack/platform shards used in CI:

```powershell
powershell -ExecutionPolicy Bypass -File .\suite.ps1 -Action check -CheckMode smoke -CheckShard portable -Stack go
powershell -ExecutionPolicy Bypass -File .\suite.ps1 -Action check -CheckMode build -CheckShard windows -Stack dotnet
```

GitHub Actions runs portable stack shards on Ubuntu, deterministic Windows-capture/demo smokes for Go, Rust, and .NET, and Windows product build/smoke shards on Windows. Build contracts run checked-in Python, Node.js, Rust, and Go tests in addition to compilation.

Inspect environment readiness across every stack in the suite:

```powershell
powershell -ExecutionPolicy Bypass -File .\suite.ps1 -Action doctor
powershell -ExecutionPolicy Bypass -File .\suite.ps1 -Action doctor -DoctorFormat markdown -OutputPath .\docs\doctor-report.md
```

The doctor report is useful before onboarding to the repo on a new machine because it shows which runtimes are present, which command will be used for each stack, which tools are currently runnable, and whether each tool has a configured smoke check. C++ tools fall back to `zig c++` automatically when `g++` is not installed, which matches the Windows-first toolchain already used elsewhere in this workspace.

## Near-Term Consolidation Plan

1. Normalize README sections so each utility has the same install, run, sample data, and verification shape.
2. Add deterministic capture modes to the remaining host-dependent Windows utilities where captured inputs can faithfully represent the real workflow.
3. Decide which older standalone repos should stay archived publicly and which should redirect here.

## Portfolio Positioning

This repo should be the visible portfolio surface for small CLI utilities. Individual tools can still be useful internally, but the public story should be a maintained suite instead of a long row of tiny project cards.
