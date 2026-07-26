# Workspace Branch Watch

Practical C++ command-line utility that scans a folder of git repositories and turns branch drift into a short review queue.

## Why this exists

When several repos live in one workspace, it gets easy to miss the ones that are dirty, behind their upstream, or quietly stale. This tool scans a root folder for nested git repositories and summarizes:

- current branch per repo
- default branch inferred from `origin/HEAD` when available
- ahead/behind counts versus the tracked upstream
- tracked and untracked change counts
- days since the last commit
- concise status labels like `dirty`, `drifted`, or `stale`
- optional Markdown export for a morning workspace review

It does not modify any repo. The goal is to make repo hygiene visible before a push or before starting new work.

## Build

```bash
g++ -std=c++17 -O2 -Wall -Wextra -pedantic main.cpp -o workspace-branch-watch
```

## Usage

Scan the current workspace:

```bash
workspace-branch-watch C:\Users\abhim\Desktop\abhiportfoliorepogroup
```

Tighten the stale threshold and write a Markdown report:

```bash
workspace-branch-watch C:\Users\abhim\Desktop\abhiportfoliorepogroup --stale-days 14 --markdown-out reports\workspace-watch.md
```

Skip noisy folders that should not be scanned:

```bash
workspace-branch-watch C:\Users\abhim\Desktop\abhiportfoliorepogroup --exclude-dir node_modules --exclude-dir vendor
```

## Sample console output

```text
Workspace Branch Watch
Root: C:\Users\abhim\Desktop\abhiportfoliorepogroup
Repositories scanned: 8
Dirty: 2 | Drifted: 3 | Stale: 1

attention  dirty changes   5 | behind 1 | main | projects\calendar-conflict-scout
ready      clean           0 | synced   | main | projects\workspace-branch-watch
```

## Portfolio Positioning

- Project type: C++ command-line utility
- Direction fit: practical software for real multi-repo workflow management
- Best demo: scan a project workspace and show which repos need action before work starts
