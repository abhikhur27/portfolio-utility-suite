# Shell History Risk Auditor

Rust CLI that scans shell history files for risky command patterns before they turn into quiet operational or security debt.

## Why this exists

Shell history is useful until it becomes an accidental archive of:

- destructive commands
- force-push and reset habits
- inline secrets and bearer tokens
- `curl | sh` style remote execution
- history-clearing commands that hide prior context

This tool gives one short audit pass across PowerShell, Bash, Zsh, Fish, or Nushell history files and turns the risky lines into a reviewable brief.

## What it checks

- destructive filesystem or disk commands such as `rm -rf`, `rd /s /q`, and `format`
- forceful git operations such as `git reset --hard` and `git push --force`
- remote script execution pipelines such as `irm ... | iex` or `curl ... | bash`
- secret-like tokens embedded directly in history
- inline credential helpers such as `sshpass`
- history-clearing commands

## Usage

Audit one file:

```bash
cargo run -- C:\Users\name\AppData\Roaming\Microsoft\Windows\PowerShell\PSReadLine\ConsoleHost_history.txt
```

Audit a directory tree and export Markdown + JSON:

```bash
cargo run -- C:\Users\name --markdown-out reports\history-risk.md --json-out reports\history-risk.json
```

## Output

- console summary with high / medium / low finding counts
- top risky commands with file path and line number
- optional Markdown and JSON reports for review or follow-up cleanup

## Portfolio Positioning

- Project type: Rust CLI utility
- Lane: Windows / shell workflow security
- Best use: audit your own history before syncing dotfiles, sharing a machine, or cleaning up old terminal habits

## Verification

```bash
cargo test
cargo run -- . --markdown-out reports\sample.md --json-out reports\sample.json
```
