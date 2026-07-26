# PDF Annotation Digest

Python CLI that extracts annotations from a PDF and turns them into a Markdown reading brief plus structured JSON.

## Why it exists

Research and course PDFs often accumulate sticky notes, highlights, and margin comments, but those annotations are hard to review in one pass. This tool pulls them into one digest so the reading follow-up can happen outside the PDF viewer.

## What it does

- reads PDF annotations with `pypdf`
- counts annotation types, colors, and page hotspots
- can filter to one author or a subset of annotation kinds before exporting
- exports a Markdown reading brief for notes or handoff
- exports JSON for later scripting
- works well for highlighted papers, commented slides, and annotated handouts

## Usage

```bash
python pdf_annotation_digest.py sample_annotations.pdf --json-out reports/sample.json --markdown-out reports/sample.md
```

Filter to one reviewer and just highlights:

```bash
python pdf_annotation_digest.py sample_annotations.pdf --author "Abhi" --kind highlight --json-out reports/highlights.json
```

## Sample file

Generate the reproducible sample PDF:

```bash
python make_sample_pdf.py
```

## Verification

```bash
python -m py_compile pdf_annotation_digest.py make_sample_pdf.py
python make_sample_pdf.py
python pdf_annotation_digest.py sample_annotations.pdf --kind note --json-out reports/sample.json --markdown-out reports/sample.md
```

## Portfolio Positioning

- Project type: Python CLI utility
- Target workflow: research reading and PDF review
- Distinctive angle: converts annotation clutter into a reviewable study brief
