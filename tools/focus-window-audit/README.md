# Focus Window Audit

Windows-first `.NET` utility that samples the foreground window over time and turns the session into a focus report.

Instead of guessing where a study block went, it records which app and window actually owned the foreground, how often context switched, and where the longest uninterrupted block happened.

## What it does

- Samples the active foreground window on a configurable interval.
- Groups consecutive samples into real focus segments.
- Reports top processes and top window titles by captured time.
- Flags rapid context switches under a configurable threshold.
- Writes Markdown and JSON reports for later review.
- Includes `--demo` mode so the repo can be verified without a live capture.

## Why this is distinct

This is not another timer or Pomodoro clone. It audits actual foreground-window behavior and turns it into a session brief you can inspect after coding, studying, or debugging.

## Requirements

- Windows for live capture
- .NET SDK 10.0 or newer

## Run

Live capture for 2 minutes:

```powershell
dotnet run -- --duration-seconds 120 --interval-ms 1000 --markdown-out reports/session.md --json-out reports/session.json
```

Demo mode:

```powershell
dotnet run -- --demo --markdown-out reports/demo.md --json-out reports/demo.json
```

Keep desktop / empty-title samples instead of filtering them:

```powershell
dotnet run -- --duration-seconds 90 --include-desktop
```

## Output highlights

- Capture span in minutes
- Context switches and switches-per-hour rate
- Longest uninterrupted focus block
- Top processes by share of foreground time
- Top window titles by share of foreground time
- Rapid short-switch list
- Full segment timeline

## Example use cases

- Audit whether a homework block actually stayed in the editor and terminal.
- Compare fragmented vs focused debugging sessions.
- Export a short Markdown brief before changing study or coding habits.

## Sanity check

```powershell
dotnet build
dotnet run -- --demo --markdown-out reports/demo.md --json-out reports/demo.json
```
