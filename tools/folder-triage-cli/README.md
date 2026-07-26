# Folder Triage CLI

Practical C++ command-line utility that audits a directory tree and turns cleanup into a concrete plan instead of guesswork.

## Why this exists

Large folders like `Downloads`, coursework archives, and project scratch directories get messy fast. This tool scans a tree and surfaces:

- biggest files by footprint
- heaviest top-level directories by total bytes
- stale files older than a chosen threshold
- extension-level storage breakdown
- empty directories
- probable duplicate filename+size groups
- optional exact duplicate-content scan for stronger cleanup confidence
- optional Markdown and CSV outputs for cleanup review

It does not delete anything. The point is to produce an action list first.

## Build

With `g++`:

```bash
g++ -std=c++17 -O2 -Wall -Wextra -pedantic main.cpp -o folder-triage-cli
```

With Zig's C++ frontend:

```bash
zig c++ -std=c++17 -O2 main.cpp -o folder-triage-cli.exe
```

## Usage

Basic scan:

```bash
folder-triage-cli C:\Users\abhim\Downloads
```

Raise the review depth and stale threshold:

```bash
folder-triage-cli C:\Users\abhim\Downloads --top 15 --stale-days 60
```

Export a Markdown report and candidate CSV:

```bash
folder-triage-cli C:\Users\abhim\Downloads --report reports\downloads-triage.md --csv reports\downloads-candidates.csv
```

Turn on exact duplicate-content detection when you want a stronger dedupe pass:

```bash
folder-triage-cli C:\Users\abhim\Downloads --exact-duplicates --report reports\downloads-triage.md
```

Skip noisy directories like dependency caches or VCS metadata:

```bash
folder-triage-cli C:\Users\abhim\Downloads --exclude-dir node_modules --exclude-dir .git --report reports\downloads-triage.md
```

## Sample output

```text
Folder Triage CLI
Root:                C:\Users\abhim\Downloads
Files scanned:       418
Directories visited: 73
Total size:          9.84 GB
Empty directories:   6
Stale threshold:     45 days
Probable duplicate groups: 3
Directory hotspots:
  coursework            4.11 GB across 182 files
```

## Output artifacts

- `--report`: Markdown brief with footprint, stale candidates, duplicate groups, and empty directories
- console + Markdown reports now include top-level directory hotspots so cleanup starts with the heaviest subtree
- `--csv`: machine-readable cleanup candidates with reason, path, size, and modified date
- `--exact-duplicates`: hashes same-size files and surfaces true duplicate-content groups
- `--exclude-dir`: repeatable filter for noisy folders you do not want included in the audit

## Portfolio Positioning

- Project type: C++ command-line utility
- Direction fit: real local workflow software rather than another browser demo
- Strongest demo: scan a messy folder and show the generated Markdown cleanup brief
