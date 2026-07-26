# Build Failure Brief

Python CLI that turns noisy build and test logs into one concise failure brief.

## Why this exists

Raw CI or local build logs bury the actual blockers in a wall of repeated output. This tool pulls out the recognizable compiler and test failures, groups the hotspots, and emits either Markdown or JSON for handoff.

## What it parses

- GCC / Clang / javac style `file:line:col: error: ...`
- TypeScript `file(line,col): error TSxxxx: ...`
- GitHub Actions `::error file=...,line=...::...` annotations
- Pytest `FAILED path::test_name - ...`
- Unittest `FAIL:` / `ERROR:` blocks
- Cargo test failures plus panic summaries
- Python tracebacks with the terminal exception line

## Usage

```bash
python build_failure_brief.py build.log
python build_failure_brief.py build.log --format json
type build.log | python build_failure_brief.py -
python build_failure_brief.py build.log --output failure-brief.md
```

## Example output

```text
# Build Failure Brief

- Diagnostics found: 3
- Severities: {"error": 1, "failed": 1, "panic": 1}
- Categories: {"compiler": 1, "exception": 1, "test": 1}
```

## Local verification

```bash
python -m unittest discover -s tests -p "test_*.py"
python build_failure_brief.py --help
```

## Portfolio positioning

- Project type: Python CLI
- Honest value: build-log triage utility for local debugging and CI handoff
- Best demo move: run it on one mixed compiler/test log and show the hotspot list plus the short diagnostic brief
