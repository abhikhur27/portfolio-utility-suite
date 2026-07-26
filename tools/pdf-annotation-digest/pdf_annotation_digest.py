#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pypdf import PdfReader


ANNOTATION_LABELS = {
    "/Highlight": "highlight",
    "/Text": "note",
    "/Underline": "underline",
    "/Squiggly": "squiggly",
    "/StrikeOut": "strikeout",
    "/FreeText": "free-text",
}


@dataclass
class AnnotationRow:
    page: int
    kind: str
    author: str
    contents: str
    modified: str
    color: str
    rect: list[float]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract PDF annotations into a Markdown and JSON reading digest."
    )
    parser.add_argument("input_pdf", type=Path, help="Path to the annotated PDF.")
    parser.add_argument(
        "--author",
        action="append",
        default=[],
        help="Only include annotations from the given author. Repeatable.",
    )
    parser.add_argument(
        "--kind",
        action="append",
        default=[],
        help="Only include the given annotation kind such as highlight, note, or underline. Repeatable.",
    )
    parser.add_argument("--json-out", type=Path, help="Optional JSON export path.")
    parser.add_argument("--markdown-out", type=Path, help="Optional Markdown digest export path.")
    return parser.parse_args()


def color_label(raw_color: Any) -> str:
    if not raw_color:
        return "unspecified"
    try:
        channels = [float(channel) for channel in raw_color]
    except TypeError:
        return "unspecified"
    rounded = [max(0, min(255, round(channel * 255))) for channel in channels[:3]]
    if len(rounded) < 3:
        return "unspecified"
    return "#{:02x}{:02x}{:02x}".format(*rounded)


def rect_values(raw_rect: Any) -> list[float]:
    if not raw_rect:
        return []
    return [round(float(value), 2) for value in raw_rect]


def extract_annotations(path: Path) -> list[AnnotationRow]:
    reader = PdfReader(path)
    annotations: list[AnnotationRow] = []
    for page_index, page in enumerate(reader.pages, start=1):
        annotation_refs = page.get("/Annots") or []
        for annotation_ref in annotation_refs:
            annotation = annotation_ref.get_object()
            subtype = str(annotation.get("/Subtype", "/Unknown"))
            annotations.append(
                AnnotationRow(
                    page=page_index,
                    kind=ANNOTATION_LABELS.get(subtype, subtype.removeprefix("/").lower()),
                    author=str(annotation.get("/T", "")).strip(),
                    contents=str(annotation.get("/Contents", "")).strip(),
                    modified=str(annotation.get("/M", "")).strip(),
                    color=color_label(annotation.get("/C")),
                    rect=rect_values(annotation.get("/Rect")),
                )
            )
    return annotations


def filter_annotations(
    annotations: list[AnnotationRow],
    authors: list[str],
    kinds: list[str],
) -> list[AnnotationRow]:
    normalized_authors = {author.strip().lower() for author in authors if author.strip()}
    normalized_kinds = {kind.strip().lower() for kind in kinds if kind.strip()}
    if not normalized_authors and not normalized_kinds:
        return annotations

    filtered = []
    for annotation in annotations:
        if normalized_authors and annotation.author.strip().lower() not in normalized_authors:
            continue
        if normalized_kinds and annotation.kind.strip().lower() not in normalized_kinds:
            continue
        filtered.append(annotation)
    return filtered


def build_report(path: Path, annotations: list[AnnotationRow]) -> dict[str, Any]:
    kind_counts = Counter(annotation.kind for annotation in annotations)
    page_counts = Counter(annotation.page for annotation in annotations)
    author_counts = Counter(annotation.author for annotation in annotations if annotation.author)
    color_counts = Counter(annotation.color for annotation in annotations if annotation.color != "unspecified")
    return {
        "input_pdf": str(path.resolve()),
        "annotation_count": len(annotations),
        "pages_with_annotations": len(page_counts),
        "kind_counts": dict(sorted(kind_counts.items())),
        "author_counts": dict(sorted(author_counts.items())),
        "color_counts": dict(sorted(color_counts.items())),
        "page_hotspots": [
            {"page": page, "annotations": count}
            for page, count in page_counts.most_common()
        ],
        "annotations": [asdict(annotation) for annotation in annotations],
    }


def write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# PDF Annotation Digest",
        "",
        f"- Input: `{report['input_pdf']}`",
        f"- Annotation count: `{report['annotation_count']}`",
        f"- Pages with annotations: `{report['pages_with_annotations']}`",
        "",
        "## Annotation Types",
        "",
    ]

    kind_counts = report["kind_counts"]
    if kind_counts:
        for kind, count in kind_counts.items():
            lines.append(f"- `{kind}`: {count}")
    else:
        lines.append("- No annotations found.")

    if report["color_counts"]:
        lines.extend(["", "## Colors", ""])
        for color, count in report["color_counts"].items():
            lines.append(f"- `{color}`: {count}")

    if report["author_counts"]:
        lines.extend(["", "## Authors", ""])
        for author, count in report["author_counts"].items():
            lines.append(f"- `{author}`: {count}")

    if report["page_hotspots"]:
        lines.extend(["", "## Page Hotspots", ""])
        for row in report["page_hotspots"]:
            lines.append(f"- Page {row['page']}: {row['annotations']} annotations")

    if report["annotations"]:
        lines.extend(["", "## Annotation Details", ""])
        for row in report["annotations"]:
            header = f"### Page {row['page']} | {row['kind']}"
            lines.append(header)
            lines.append("")
            if row["author"]:
                lines.append(f"- Author: `{row['author']}`")
            if row["modified"]:
                lines.append(f"- Modified: `{row['modified']}`")
            lines.append(f"- Color: `{row['color']}`")
            if row["rect"]:
                rect_text = ", ".join(str(value) for value in row["rect"])
                lines.append(f"- Bounds: `{rect_text}`")
            lines.append(f"- Note: {row['contents'] or '(empty)' }")
            lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    if not args.input_pdf.exists():
        raise SystemExit(f"Input file not found: {args.input_pdf}")

    annotations = filter_annotations(extract_annotations(args.input_pdf), args.author, args.kind)
    report = build_report(args.input_pdf, annotations)

    print("PDF Annotation Digest")
    print("=====================")
    print(f"Input:                {report['input_pdf']}")
    print(f"Annotation count:     {report['annotation_count']}")
    print(f"Pages with notes:     {report['pages_with_annotations']}")
    if args.author:
        print(f"Author filter:        {', '.join(args.author)}")
    if args.kind:
        print(f"Kind filter:          {', '.join(args.kind)}")
    if report["page_hotspots"]:
        hottest = report["page_hotspots"][0]
        print(f"Hottest page:         {hottest['page']} ({hottest['annotations']} annotations)")

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Wrote JSON report:    {args.json_out}")

    if args.markdown_out:
        write_markdown(report, args.markdown_out)
        print(f"Wrote Markdown brief: {args.markdown_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
