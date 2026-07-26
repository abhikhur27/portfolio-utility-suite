#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

CITATION_PATTERNS = [
    re.compile(r"\[@[^\]]+\]"),
    re.compile(r"\[[0-9,\s\-]+\]"),
    re.compile(r"\([A-Z][A-Za-z'`\-]+(?: et al\.)?,?\s+\d{4}[a-z]?\)"),
]
CLAIM_CUES = {
    "improves",
    "increase",
    "increases",
    "decrease",
    "decreases",
    "outperform",
    "outperforms",
    "reduces",
    "shows",
    "demonstrates",
    "achieves",
    "yields",
    "correlates",
    "predicts",
    "causes",
    "faster",
    "lower",
    "higher",
    "better",
}


@dataclass
class Finding:
    file: str
    section: str
    line: int
    word_count: int
    severity: int
    cues: list[str]
    excerpt: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit markdown notes for claim-heavy passages that appear to lack citations."
    )
    parser.add_argument("--input", type=Path, required=True, help="Markdown file or directory to scan.")
    parser.add_argument("--json-out", type=Path, help="Optional JSON export path.")
    parser.add_argument("--markdown-out", type=Path, help="Optional Markdown export path.")
    parser.add_argument("--min-words", type=int, default=14, help="Minimum words before a paragraph counts as claim-heavy.")
    parser.add_argument("--include-frontmatter", action="store_true", help="Audit YAML frontmatter instead of skipping it.")
    parser.add_argument("--include-code-fences", action="store_true", help="Audit fenced code blocks instead of skipping them.")
    parser.add_argument("--fail-on-findings", action="store_true", help="Exit with code 2 when uncited claim-heavy passages are found.")
    return parser.parse_args()


def load_markdown_files(target: Path) -> list[Path]:
    if target.is_file():
        return [target]
    if target.is_dir():
        return sorted(path for path in target.rglob("*.md") if path.is_file())
    raise FileNotFoundError(f"Input path not found: {target}")


def has_citation(text: str) -> bool:
    return any(pattern.search(text) for pattern in CITATION_PATTERNS)


def looks_claim_heavy(text: str, min_words: int) -> tuple[bool, list[str]]:
    cleaned = " ".join(text.split())
    words = re.findall(r"[A-Za-z0-9']+", cleaned)
    lower_words = [word.lower() for word in words]
    cues = sorted({word for word in lower_words if word in CLAIM_CUES})
    has_number = any(char.isdigit() for char in cleaned)
    return len(words) >= min_words or has_number or bool(cues), cues


def iter_blocks(content: str) -> list[tuple[str, int, str]]:
    section = "Intro"
    blocks: list[tuple[str, int, str]] = []
    pending: list[str] = []
    block_start = 1

    def flush() -> None:
        nonlocal pending
        if not pending:
            return
        blocks.append((section, block_start, " ".join(line.strip() for line in pending)))
        pending = []

    for index, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            flush()
            heading = stripped.lstrip("#").strip()
            section = heading or section
            continue

        if not stripped:
            flush()
            continue

        if stripped.startswith(("- ", "* ")):
            flush()
            blocks.append((section, index, stripped[2:].strip()))
            continue

        if not pending:
            block_start = index
        pending.append(stripped)

    flush()
    return blocks


def strip_frontmatter_and_code_fences(
    content: str, *, include_frontmatter: bool, include_code_fences: bool
) -> str:
    lines = content.splitlines()
    cleaned: list[str] = []
    in_frontmatter = False
    in_code_fence = False

    for index, line in enumerate(lines):
        stripped = line.strip()

        if not include_frontmatter and index == 0 and stripped == "---":
            in_frontmatter = True
            cleaned.append("")
            continue
        if in_frontmatter:
            if stripped == "---":
                in_frontmatter = False
            cleaned.append("")
            continue

        if not include_code_fences and stripped.startswith("```"):
            in_code_fence = not in_code_fence
            cleaned.append("")
            continue
        if in_code_fence:
            cleaned.append("")
            continue

        cleaned.append(line)

    return "\n".join(cleaned)


def audit_file(
    path: Path,
    root: Path,
    min_words: int,
    *,
    include_frontmatter: bool,
    include_code_fences: bool,
) -> list[Finding]:
    content = path.read_text(encoding="utf-8", errors="ignore")
    content = strip_frontmatter_and_code_fences(
        content,
        include_frontmatter=include_frontmatter,
        include_code_fences=include_code_fences,
    )
    findings: list[Finding] = []
    for section, line, block in iter_blocks(content):
        if has_citation(block):
            continue
        looks_heavy, cues = looks_claim_heavy(block, min_words)
        if not looks_heavy:
            continue
        word_count = len(re.findall(r"[A-Za-z0-9']+", block))
        severity = min(5, 1 + len(cues) + (1 if any(char.isdigit() for char in block) else 0) + (1 if word_count >= min_words + 10 else 0))
        findings.append(
            Finding(
                file=path.relative_to(root).as_posix(),
                section=section,
                line=line,
                word_count=word_count,
                severity=severity,
                cues=cues,
                excerpt=block[:220],
            )
        )
    return findings


def build_report(
    target: Path,
    min_words: int,
    *,
    include_frontmatter: bool,
    include_code_fences: bool,
) -> dict[str, object]:
    files = load_markdown_files(target)
    root = target if target.is_dir() else target.parent
    findings = [
        finding
        for path in files
        for finding in audit_file(
            path,
            root,
            min_words,
            include_frontmatter=include_frontmatter,
            include_code_fences=include_code_fences,
        )
    ]
    findings.sort(key=lambda finding: (-finding.severity, -finding.word_count, finding.file, finding.line))

    file_counts = Counter(finding.file for finding in findings)
    section_counts: dict[str, int] = defaultdict(int)
    for finding in findings:
        section_counts[f"{finding.file} :: {finding.section}"] += 1

    return {
        "input": str(target.resolve()),
        "files_scanned": len(files),
        "finding_count": len(findings),
        "min_words": min_words,
        "frontmatter_scanned": include_frontmatter,
        "code_fences_scanned": include_code_fences,
        "top_files": file_counts.most_common(8),
        "top_sections": sorted(section_counts.items(), key=lambda item: (-item[1], item[0]))[:10],
        "findings": [asdict(finding) for finding in findings],
    }


def render_markdown(report: dict[str, object]) -> str:
    lines = [
        "# Citation Gap Audit",
        "",
        f"- Input: `{report['input']}`",
        f"- Markdown files scanned: `{report['files_scanned']}`",
        f"- Claim-heavy passages without citations: `{report['finding_count']}`",
        f"- Minimum word threshold: `{report['min_words']}`",
        f"- Frontmatter scanned: `{report['frontmatter_scanned']}`",
        f"- Code fences scanned: `{report['code_fences_scanned']}`",
        "",
        "## Hot Files",
        "",
    ]

    top_files = report["top_files"]
    if top_files:
        for file_name, count in top_files:
            lines.append(f"- `{file_name}`: {count} uncited passage(s)")
    else:
        lines.append("- No uncited claim-heavy passages detected.")

    lines.extend(["", "## Sample Findings", ""])
    findings = report["findings"]
    if findings:
        for finding in findings[:12]:
            cue_text = ", ".join(finding["cues"]) if finding["cues"] else "length/number heuristic"
            lines.append(
                f"- `{finding['file']}` line {finding['line']} in **{finding['section']}** "
                f"(severity {finding['severity']}/5, {finding['word_count']} words, cues: {cue_text})"
            )
            lines.append(f"  {finding['excerpt']}")
    else:
        lines.append("- None.")

    return "\n".join(lines)


def print_report(report: dict[str, object]) -> None:
    print("Citation Gap Auditor")
    print("====================")
    print(f"Input:                 {report['input']}")
    print(f"Markdown files:        {report['files_scanned']}")
    print(f"Uncited claim blocks:  {report['finding_count']}")
    print(f"Minimum words:         {report['min_words']}")
    print(f"Frontmatter scanned:   {report['frontmatter_scanned']}")
    print(f"Code fences scanned:   {report['code_fences_scanned']}")

    findings = report["findings"]
    if findings:
        print("\nTop findings:")
        for finding in findings[:8]:
            cue_text = ", ".join(finding["cues"]) if finding["cues"] else "length/number heuristic"
            print(
                f"  {finding['file']}:{finding['line']} [{finding['section']}] "
                f"severity {finding['severity']}/5 | {finding['word_count']} words | {cue_text}"
            )


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> None:
    args = parse_args()
    report = build_report(
        args.input,
        args.min_words,
        include_frontmatter=args.include_frontmatter,
        include_code_fences=args.include_code_fences,
    )
    print_report(report)

    if args.json_out:
        write_text(args.json_out, json.dumps(report, indent=2))
        print(f"\nWrote JSON report: {args.json_out}")

    if args.markdown_out:
        write_text(args.markdown_out, render_markdown(report))
        print(f"Wrote Markdown report: {args.markdown_out}")

    if args.fail_on_findings and report["finding_count"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
