# Citation Gap Auditor

Python CLI that scans markdown research notes for claim-heavy passages that appear to lack citations.

## What it does

- walks one markdown file or an entire notes directory
- identifies paragraphs and bullet points that look claim-heavy because they are long, numeric, or use research-style cue words
- skips passages that already contain common citation patterns such as `[@key]`, `[12]`, or `(Smith, 2024)`
- skips YAML frontmatter and fenced code blocks by default so config metadata and pasted snippets do not dominate the audit
- prints a console summary and can export Markdown / JSON reports for cleanup passes
- assigns a simple severity score so the highest-risk uncited passages float to the top first

## Why it is useful

Reading notes often drift into paraphrased claims without a source marker nearby. This tool gives you a fast review pass before you turn notes into study guides, literature surveys, or project writeups.

## Usage

```bash
python auditor.py --input samples --markdown-out reports/sample-report.md --json-out reports/sample-report.json
```

Fail a CI check when findings remain:

```bash
python auditor.py --input samples --fail-on-findings
```

## Output

- console summary with the hottest files first
- Markdown brief for review
- JSON export for scripting or editor integrations

## Verification

```bash
python auditor.py --input samples --markdown-out reports/self-check.md --json-out reports/self-check.json
```

## Portfolio Positioning

- Project type: Python CLI research workflow utility
- Target workflow: clean up reading notes before reusing claims in papers, docs, or presentations
- Direction fit: practical non-browser tooling with a literature/research angle
