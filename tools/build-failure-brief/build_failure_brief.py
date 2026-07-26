from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


COMPILER_RE = re.compile(
    r"^(?P<file>.+?):(?P<line>\d+)(?::(?P<column>\d+))?:\s(?P<severity>fatal error|error|warning|note):\s(?P<message>.+)$"
)
TSC_RE = re.compile(
    r"^(?P<file>.+?)\((?P<line>\d+),(?P<column>\d+)\):\s(?P<severity>error|warning)\s(?P<code>TS\d+):\s(?P<message>.+)$"
)
PYTEST_RE = re.compile(r"^FAILED\s(?P<test>[^\s]+)\s-\s(?P<message>.+)$")
UNITTEST_RE = re.compile(r"^(FAIL|ERROR):\s(?P<test>.+)$")
CARGO_RE = re.compile(r"^test\s(?P<test>[^\s]+)\s\.\.\.\sFAILED$")
PANIC_RE = re.compile(r"^thread '([^']+)' panicked at (?P<message>.+)$")
GITHUB_ACTIONS_RE = re.compile(
    r"^::(?P<severity>error|warning)\s+file=(?P<file>[^,\n]+)(?:,line=(?P<line>\d+))?(?:,col=(?P<column>\d+))?::(?P<message>.+)$"
)
PYTHON_TRACEBACK_RE = re.compile(
    r'^\s*File "(?P<file>.+?)", line (?P<line>\d+)(?:, in (?P<function>.+))?$'
)


@dataclass
class Diagnostic:
    kind: str
    severity: str
    subject: str
    message: str
    line: int | None = None
    column: int | None = None
    code: str | None = None


def parse_diagnostics(text: str) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    pending_test: str | None = None
    pending_traceback: tuple[str, int] | None = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue

        github_actions_match = GITHUB_ACTIONS_RE.match(line)
        if github_actions_match:
            diagnostics.append(
                Diagnostic(
                    kind="compiler",
                    severity=github_actions_match.group("severity"),
                    subject=github_actions_match.group("file"),
                    message=github_actions_match.group("message"),
                    line=int(github_actions_match.group("line")) if github_actions_match.group("line") else None,
                    column=int(github_actions_match.group("column")) if github_actions_match.group("column") else None,
                )
            )
            pending_test = None
            pending_traceback = None
            continue

        traceback_match = PYTHON_TRACEBACK_RE.match(line)
        if traceback_match:
            pending_traceback = (
                traceback_match.group("file"),
                int(traceback_match.group("line")),
            )
            continue

        if pending_traceback and not line.startswith("Traceback"):
            if line.startswith((" ", "\t")):
                continue
            if ":" in line:
                exception_name, _, message = line.partition(":")
                diagnostics.append(
                    Diagnostic(
                        kind="exception",
                        severity=exception_name.strip(),
                        subject=pending_traceback[0],
                        message=message.strip() or exception_name.strip(),
                        line=pending_traceback[1],
                    )
                )
                pending_traceback = None
                pending_test = None
                continue
            pending_traceback = None

        compiler_match = COMPILER_RE.match(line)
        if compiler_match:
            diagnostics.append(
                Diagnostic(
                    kind="compiler",
                    severity=compiler_match.group("severity"),
                    subject=compiler_match.group("file"),
                    message=compiler_match.group("message"),
                    line=int(compiler_match.group("line")),
                    column=int(compiler_match.group("column")) if compiler_match.group("column") else None,
                )
            )
            pending_test = None
            pending_traceback = None
            continue

        tsc_match = TSC_RE.match(line)
        if tsc_match:
            diagnostics.append(
                Diagnostic(
                    kind="compiler",
                    severity=tsc_match.group("severity"),
                    subject=tsc_match.group("file"),
                    message=tsc_match.group("message"),
                    line=int(tsc_match.group("line")),
                    column=int(tsc_match.group("column")),
                    code=tsc_match.group("code"),
                )
            )
            pending_test = None
            pending_traceback = None
            continue

        pytest_match = PYTEST_RE.match(line)
        if pytest_match:
            diagnostics.append(
                Diagnostic(
                    kind="test",
                    severity="failed",
                    subject=pytest_match.group("test"),
                    message=pytest_match.group("message"),
                )
            )
            pending_test = None
            pending_traceback = None
            continue

        unittest_match = UNITTEST_RE.match(line)
        if unittest_match:
            diagnostics.append(
                Diagnostic(
                    kind="test",
                    severity=unittest_match.group(1).lower(),
                    subject=unittest_match.group("test"),
                    message="Unit test reported a failure block.",
                )
            )
            pending_test = unittest_match.group("test")
            pending_traceback = None
            continue

        cargo_match = CARGO_RE.match(line)
        if cargo_match:
            pending_test = cargo_match.group("test")
            diagnostics.append(
                Diagnostic(
                    kind="test",
                    severity="failed",
                    subject=pending_test,
                    message="Cargo test reported a failure.",
                )
            )
            pending_traceback = None
            continue

        panic_match = PANIC_RE.match(line)
        if panic_match and pending_test:
            diagnostics.append(
                Diagnostic(
                    kind="exception",
                    severity="panic",
                    subject=pending_test,
                    message=panic_match.group("message"),
                )
            )
            pending_test = None
            pending_traceback = None
            continue

    return diagnostics


def build_summary(diagnostics: Iterable[Diagnostic]) -> dict[str, object]:
    rows = list(diagnostics)
    severity_counts = Counter(row.severity for row in rows)
    kind_counts = Counter(row.kind for row in rows)
    subject_counts = Counter(row.subject for row in rows)
    top_subjects = [
        {"subject": subject, "count": count}
        for subject, count in subject_counts.most_common(5)
    ]

    return {
        "diagnosticCount": len(rows),
        "severityCounts": dict(severity_counts),
        "kindCounts": dict(kind_counts),
        "topSubjects": top_subjects,
    }


def to_markdown(diagnostics: list[Diagnostic]) -> str:
    summary = build_summary(diagnostics)
    lines = [
        "# Build Failure Brief",
        "",
        f"- Diagnostics found: {summary['diagnosticCount']}",
        f"- Severities: {json.dumps(summary['severityCounts'], sort_keys=True)}",
        f"- Categories: {json.dumps(summary['kindCounts'], sort_keys=True)}",
        "",
        "## Hotspots",
    ]

    hotspots = summary["topSubjects"] or []
    if hotspots:
        lines.extend(f"- `{entry['subject']}` ({entry['count']})" for entry in hotspots)
    else:
        lines.append("- No hotspots detected.")

    lines.extend(["", "## Diagnostics"])
    if not diagnostics:
        lines.append("- No recognizable compiler or test failures were found.")
        return "\n".join(lines)

    for index, entry in enumerate(diagnostics, start=1):
        location = ""
        if entry.line is not None:
            location = f" @ line {entry.line}"
            if entry.column is not None:
                location += f", col {entry.column}"
        code_suffix = f" [{entry.code}]" if entry.code else ""
        lines.append(
            f"{index}. `{entry.subject}`{location} - {entry.kind}/{entry.severity}{code_suffix}: {entry.message}"
        )

    return "\n".join(lines)


def to_json_payload(diagnostics: list[Diagnostic]) -> str:
    payload = {
        "summary": build_summary(diagnostics),
        "diagnostics": [asdict(entry) for entry in diagnostics],
    }
    return json.dumps(payload, indent=2)


def read_input(path_arg: str | None) -> str:
    if not path_arg or path_arg == "-":
        return sys.stdin.read()
    return Path(path_arg).read_text(encoding="utf-8")


def write_output(body: str, output_path: str | None) -> None:
    if output_path:
        Path(output_path).write_text(body, encoding="utf-8")
        return
    sys.stdout.write(body)
    if not body.endswith("\n"):
        sys.stdout.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Turn build or test logs into a concise failure brief."
    )
    parser.add_argument(
        "input",
        nargs="?",
        help="Path to a log file. Omit or use - to read from stdin.",
    )
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="Output format.",
    )
    parser.add_argument(
        "--output",
        help="Optional output file path. Defaults to stdout.",
    )
    args = parser.parse_args()

    text = read_input(args.input)
    diagnostics = parse_diagnostics(text)
    body = to_markdown(diagnostics) if args.format == "markdown" else to_json_payload(diagnostics)
    write_output(body, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
