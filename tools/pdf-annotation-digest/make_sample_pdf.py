#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from pypdf import PdfWriter
from pypdf.annotations import Highlight, Text
from pypdf.generic import ArrayObject, FloatObject


def quad_points(left: float, bottom: float, right: float, top: float) -> ArrayObject:
    return ArrayObject(
        [
            FloatObject(left),
            FloatObject(top),
            FloatObject(right),
            FloatObject(top),
            FloatObject(left),
            FloatObject(bottom),
            FloatObject(right),
            FloatObject(bottom),
        ]
    )


def main() -> int:
    target = Path("sample_annotations.pdf")
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_blank_page(width=612, height=792)
    writer.add_annotation(
        0,
        Text(rect=(72, 640, 92, 660), text="Clarify the evaluation setup in section 2."),
    )
    writer.add_annotation(
        0,
        Highlight(
            rect=(120, 620, 320, 650),
            quad_points=quad_points(120, 620, 320, 650),
            highlight_color="f3b35b",
        ),
    )
    writer.add_annotation(
        1,
        Text(rect=(72, 540, 92, 560), text="Revisit the appendix proof before presentation."),
    )

    with target.open("wb") as handle:
        writer.write(handle)

    print(target.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
