from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Sequence

from ai_manuscript_repair.models import ConsistencyMark, DirectEdit
from ai_manuscript_repair.pdf_io import (
    extract_page_packets,
    locate_text,
    render_minimal_pdf,
    write_minimal_markdown,
)
from ai_manuscript_repair.review import consolidate_clusters, run_reviews


def write_jsonl(path: Path, records: Sequence[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for record in records:
        if hasattr(record, "model_dump"):
            payload = record.model_dump(mode="json")
        else:
            payload = record
        lines.append(json.dumps(payload, ensure_ascii=False))
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def parse_pages(spec: str | None, page_count: int) -> list[int] | None:
    if spec is None:
        return None
    selected: set[int] = set()
    for chunk in spec.split(","):
        token = chunk.strip()
        if not token:
            continue
        if "-" in token:
            start_text, end_text = token.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            if start > end:
                raise ValueError(f"invalid descending page range: {token}")
            selected.update(range(start - 1, end))
        else:
            selected.add(int(token) - 1)
    ordered = sorted(selected)
    if not ordered:
        raise ValueError("page selection is empty")
    if ordered[0] < 0 or ordered[-1] >= page_count:
        raise ValueError("page selection falls outside source PDF")
    return ordered


async def run_pipeline_async(
    input_pdf: Path,
    output_dir: Path,
    *,
    page_indexes: Sequence[int] | None = None,
    model: str = "gpt-5.6-sol",
    reasoning_effort: str = "medium",
    concurrency: int = 3,
    batch_size: int = 8,
    context_pages: int = 1,
    retries: int = 1,
    include_consistency: bool = False,
) -> dict[str, object]:
    input_pdf = input_pdf.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    packets = extract_page_packets(input_pdf, page_indexes)
    by_id = {item.packet_id: item for item in packets}

    direct_reviews, consistency_reviews = await run_reviews(
        packets,
        output_dir,
        model=model,
        reasoning_effort=reasoning_effort,
        concurrency=concurrency,
        batch_size=batch_size,
        context_pages=context_pages,
        retries=retries,
        include_consistency=include_consistency,
    )

    direct_edits: list[DirectEdit] = []
    edit_number = 0
    for batch_review in direct_reviews:
        for page_review in page_review_order(batch_review.reviews):
            packet = by_id[page_review.packet_id]
            for draft in page_review.edits:
                edit_number += 1
                direct_edits.append(
                    DirectEdit(
                        edit_id=f"DME-{edit_number:05d}",
                        packet_id=packet.packet_id,
                        pdf_page_index=packet.pdf_page_index,
                        rects=locate_text(
                            packet, draft.original_text, draft.occurrence_index
                        ),
                        **draft.model_dump(),
                    )
                )

    clusters = consolidate_clusters(consistency_reviews)
    marks: list[ConsistencyMark] = []
    mark_number = 0
    for cluster in clusters:
        for occurrence in cluster.occurrences:
            mark_number += 1
            packet = by_id[occurrence.packet_id]
            marks.append(
                ConsistencyMark(
                    mark_id=f"LCM-{mark_number:05d}",
                    cluster_id=cluster.cluster_id,
                    rects=locate_text(
                        packet,
                        occurrence.original_text,
                        occurrence.occurrence_index,
                    ),
                    **occurrence.model_dump(),
                )
            )

    output_pdf = output_dir / "minimal-edits.pdf"
    output_markdown = output_dir / "minimal-edits.md"
    render_minimal_pdf(
        input_pdf,
        output_pdf,
        direct_edits,
        marks,
        page_indexes=page_indexes,
    )
    write_minimal_markdown(output_markdown, direct_edits)
    write_jsonl(output_dir / "run" / "direct-edits.jsonl", direct_edits)
    if include_consistency:
        write_jsonl(output_dir / "run" / "consistency-clusters.jsonl", clusters)
        write_jsonl(output_dir / "run" / "consistency-marks.jsonl", marks)

    summary = {
        "schema_version": "1.0.0",
        "input_pdf": str(input_pdf),
        "selected_page_count": len(packets),
        "direct_edit_count": len(direct_edits),
        "consistency_enabled": include_consistency,
        "consistency_cluster_count": len(clusters),
        "consistency_mark_count": len(marks),
        "model": model,
        "reasoning_effort": reasoning_effort,
        "output_pdf": str(output_pdf),
        "output_markdown": str(output_markdown),
    }
    (output_dir / "run" / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def page_review_order(reviews):
    return sorted(reviews, key=lambda item: item.pdf_page_index)


def run_pipeline(
    input_pdf: Path,
    output_dir: Path,
    **kwargs,
) -> dict[str, object]:
    return asyncio.run(run_pipeline_async(input_pdf, output_dir, **kwargs))
