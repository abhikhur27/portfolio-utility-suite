# Vault Link Auditor

Practical Python CLI for auditing an Obsidian-style markdown vault before broken links, duplicate note names, and orphan pages quietly erode the graph.

## Why this exists

Large note vaults drift over time:

- renamed notes leave stale wikilinks behind
- duplicate titles create ambiguous references
- orphan notes pile up and become hard to rediscover

This tool turns that sprawl into a clean report you can fix in one pass.

## What it checks

- broken `[[wikilinks]]`
- broken relative markdown links like `[doc](folder/file.md)`
- broken heading anchors such as `[[note#section]]` or `[jump](note.md#section)` when the note exists but the target section does not
- missing embedded assets such as `![[diagram.png]]` or `[handout](docs/notes.pdf)` without flagging valid non-note files as broken notes
- likely repair targets for broken links based on nearby note names and titles
- ambiguous links that could resolve to multiple notes
- duplicate note titles
- orphan notes with zero inbound links
- optional Markdown or JSON export for dashboards, handoffs, or scripted cleanup
- hotspot summaries for notes that emit the most broken or ambiguous links

## Usage

```bash
python auditor.py --root example_vault
```

Write the full report to JSON:

```bash
python auditor.py --root example_vault --json-out reports/audit.json
```

Write a shareable Markdown cleanup brief:

```bash
python auditor.py --root example_vault --markdown-out reports/audit.md
```

Skip orphan-note reporting when you only care about link breakage:

```bash
python auditor.py --root example_vault --hide-orphans
```

Exclude templates or archive folders from the audit:

```bash
python auditor.py --root example_vault --exclude-glob templates/** --exclude-glob archive/**
```

## Example output

```text
Vault Link Auditor
==================
Root:              ...\example_vault
Markdown notes:    5
Broken links:      2
Ambiguous links:   1
Duplicate titles:  1
Orphan notes:      1
```

Broken-link rows now include likely repair targets when the intended note is close to an existing title or filename.

## Repository layout

- `auditor.py`: CLI entrypoint and audit logic
- `example_vault/`: small reproducible markdown sample
- `reports/`: optional exported JSON output

## Portfolio positioning

- Project type: Python CLI utility
- Target workflow: markdown / Obsidian vault maintenance
- Verification path: run the CLI on `example_vault` or your real vault root
