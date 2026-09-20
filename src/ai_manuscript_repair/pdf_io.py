from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable, Sequence

import pdfplumber

from ai_manuscript_repair.models import (
    ConsistencyMark,
    DirectEdit,
    Glyph,
    PagePacket,
    Rect,
    compact_text,
)


def _packet_hash(page_index: int, text: str, glyphs: list[Glyph]) -> str:
    payload = "\n".join(
        [
            str(page_index),
            text,
            *(
                f"{item.text}|{item.rect.x0:.4f}|{item.rect.top:.4f}|"
                f"{item.rect.x1:.4f}|{item.rect.bottom:.4f}"
                for item in glyphs
            ),
        ]
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _ordered_glyphs(chars: Iterable[dict[str, object]]) -> list[Glyph]:
    usable = [
        item
        for item in chars
        if str(item.get("text", "")) and not str(item.get("text", "")).isspace()
    ]
    usable.sort(
        key=lambda item: (
            round(float(item.get("top", 0.0)), 1),
            float(item.get("x0", 0.0)),
        )
    )
    return [
        Glyph(
            text=str(item["text"]),
            rect=Rect(
                x0=float(item["x0"]),
                top=float(item["top"]),
                x1=float(item["x1"]),
                bottom=float(item["bottom"]),
            ),
        )
        for item in usable
    ]


def extract_page_packets(
    input_pdf: Path,
    page_indexes: Sequence[int] | None = None,
) -> list[PagePacket]:
    with pdfplumber.open(input_pdf) as document:
        selected = (
            list(range(len(document.pages)))
            if page_indexes is None
            else list(page_indexes)
        )
        if selected != sorted(set(selected)):
            raise ValueError("page indexes must be sorted and unique")
        if any(index < 0 or index >= len(document.pages) for index in selected):
            raise ValueError("page index outside source PDF")
        packets: list[PagePacket] = []
        for page_index in selected:
            page = document.pages[page_index]
            page_text = page.extract_text(x_tolerance=2, y_tolerance=3) or ""
            glyphs = _ordered_glyphs(page.chars)
            if not compact_text(page_text) or not glyphs:
                raise ValueError(
                    f"PDF page {page_index + 1} has no usable text layer"
                )
            packets.append(
                PagePacket(
                    packet_id=f"AMR-P{page_index + 1:04d}",
                    pdf_page_index=page_index,
                    width=float(page.width),
                    height=float(page.height),
                    page_text=page_text,
                    glyphs=glyphs,
                    packet_sha256=_packet_hash(page_index, page_text, glyphs),
                )
            )
    return packets


def _merge_rects(rects: list[Rect]) -> list[Rect]:
    lines: list[list[Rect]] = []
    for rect in rects:
        if (
            lines
            and abs(lines[-1][0].top - rect.top) <= 1.5
            and abs(lines[-1][0].bottom - rect.bottom) <= 1.5
        ):
            lines[-1].append(rect)
        else:
            lines.append([rect])
    return [
        Rect(
            x0=min(item.x0 for item in line),
            top=min(item.top for item in line),
            x1=max(item.x1 for item in line),
            bottom=max(item.bottom for item in line),
        )
        for line in lines
    ]


def locate_text(
    packet: PagePacket,
    original_text: str,
    occurrence_index: int = 0,
) -> list[Rect]:
    needle = compact_text(original_text)
    if not needle:
        raise ValueError("cannot locate empty original text")
    stream = "".join(item.text for item in packet.glyphs)
    matches: list[int] = []
    cursor = 0
    while True:
        found = stream.find(needle, cursor)
        if found < 0:
            break
        matches.append(found)
        cursor = found + 1
    if occurrence_index >= len(matches):
        raise ValueError(
            f"text not locatable on PDF page {packet.pdf_page_index + 1}: "
            f"{original_text!r} occurrence {occurrence_index}"
        )
    start = matches[occurrence_index]
    rects = [item.rect for item in packet.glyphs[start : start + len(needle)]]
    if len(rects) != len(needle):
        raise ValueError("glyph mapping ended before located text")
    return _merge_rects(rects)


def write_minimal_markdown(path: Path, edits: Sequence[DirectEdit]) -> None:
    def cell(text: str) -> str:
        return (
            text.replace("\r\n", "\n")
            .replace("\r", "\n")
            .replace("\n", "")
            .replace("|", "\\|")
        )

    lines = ["| 页码 | 原句 | 修改 |", "|---|---|---|"]
    for edit in sorted(edits, key=lambda item: (item.pdf_page_index, item.edit_id)):
        lines.append(
            f"| PDF {edit.pdf_page_index + 1} | {cell(edit.original_text)} | "
            f"{cell(edit.corrected_text)} |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def render_minimal_pdf(
    input_pdf: Path,
    output_pdf: Path,
    edits: Sequence[DirectEdit],
    marks: Sequence[ConsistencyMark],
    page_indexes: Sequence[int] | None = None,
) -> None:
    from pypdf import PdfReader, PdfWriter
    from pypdf.annotations import Highlight
    from pypdf.generic import ArrayObject, FloatObject, NameObject, TextStringObject

    reader = PdfReader(str(input_pdf))
    selected = (
        list(range(len(reader.pages))) if page_indexes is None else list(page_indexes)
    )
    if selected != sorted(set(selected)):
        raise ValueError("page indexes must be sorted and unique")
    selected_set = set(selected)
    if not {
        *[item.pdf_page_index for item in edits],
        *[item.pdf_page_index for item in marks],
    }.issubset(selected_set):
        raise ValueError("an annotation targets a page outside the selected scope")

    edits_by_page: dict[int, list[DirectEdit]] = {}
    for item in edits:
        edits_by_page.setdefault(item.pdf_page_index, []).append(item)
    marks_by_page: dict[int, list[ConsistencyMark]] = {}
    for item in marks:
        marks_by_page.setdefault(item.pdf_page_index, []).append(item)

    writer = PdfWriter()
    for output_index, source_index in enumerate(selected):
        source_page = reader.pages[source_index]
        page_height = float(source_page.mediabox.height)
        writer.add_page(source_page)

        for mark in marks_by_page.get(source_index, []):
            for rect_number, rect in enumerate(mark.rects, start=1):
                bottom = page_height - rect.bottom
                top = page_height - rect.top
                quad_points = ArrayObject(
                    [
                        FloatObject(rect.x0),
                        FloatObject(top),
                        FloatObject(rect.x1),
                        FloatObject(top),
                        FloatObject(rect.x0),
                        FloatObject(bottom),
                        FloatObject(rect.x1),
                        FloatObject(bottom),
                    ]
                )
                annotation = Highlight(
                    rect=(rect.x0, bottom, rect.x1, top),
                    quad_points=quad_points,
                    highlight_color="fff176",
                    printing=True,
                )
                annotation[NameObject("/NM")] = TextStringObject(
                    f"{mark.mark_id}-R{rect_number:02d}"
                )
                annotation.pop(NameObject("/Contents"), None)
                annotation.pop(NameObject("/T"), None)
                writer.add_annotation(page_number=output_index, annotation=annotation)

        for edit in edits_by_page.get(source_index, []):
            for rect_number, rect in enumerate(edit.rects, start=1):
                bottom = page_height - rect.bottom
                top = page_height - rect.top
                quad_points = ArrayObject(
                    [
                        FloatObject(rect.x0),
                        FloatObject(top),
                        FloatObject(rect.x1),
                        FloatObject(top),
                        FloatObject(rect.x0),
                        FloatObject(bottom),
                        FloatObject(rect.x1),
                        FloatObject(bottom),
                    ]
                )
                annotation = Highlight(
                    rect=(rect.x0, bottom, rect.x1, top),
                    quad_points=quad_points,
                    highlight_color="e85d3f",
                    printing=True,
                    title_bar="修改",
                )
                annotation[NameObject("/Subtype")] = NameObject("/Underline")
                annotation[NameObject("/Contents")] = TextStringObject(
                    "修改为：" + edit.corrected_text.replace("\r", "").replace("\n", "")
                )
                annotation[NameObject("/NM")] = TextStringObject(
                    f"{edit.edit_id}-R{rect_number:02d}"
                )
                writer.add_annotation(page_number=output_index, annotation=annotation)

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    with output_pdf.open("wb") as stream:
        writer.write(stream)
