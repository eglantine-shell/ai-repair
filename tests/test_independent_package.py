from __future__ import annotations

import asyncio
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from pypdf import PdfReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from ai_manuscript_repair.models import (
    ConsistencyClusterDraft,
    ConsistencyMark,
    ConsistencyOccurrenceDraft,
    ConsistencyWindowReview,
    DirectEdit,
    DirectBatchReview,
    DirectPageReview,
)
from ai_manuscript_repair.pdf_io import (
    extract_page_packets,
    locate_text,
    render_minimal_pdf,
    write_minimal_markdown,
)
from ai_manuscript_repair.cli import build_parser
from ai_manuscript_repair.pipeline import parse_pages
from ai_manuscript_repair.review import consolidate_clusters, run_reviews


def build_fixture(path: Path) -> None:
    try:
        pdfmetrics.getFont("AMRTestCJK")
    except KeyError:
        pdfmetrics.registerFont(
            TTFont(
                "AMRTestCJK",
                "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
            )
        )
    document = canvas.Canvas(str(path), pagesize=(420, 600))
    document.setFont("AMRTestCJK", 12)
    document.drawString(50, 530, "用AI模拟采访者，并生成完整的访谈问题。")
    document.drawString(50, 500, "这能够有效提升企业的知识管理能力。")
    document.showPage()
    document.setFont("AMRTestCJK", 12)
    document.drawString(50, 530, "请扮演企业知识管理顾问，继续提出问题。")
    document.save()


class IndependentPackageTests(unittest.TestCase):
    def test_pdf_outputs_red_edits_and_silent_yellow_marks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.pdf"
            output = root / "minimal-edits.pdf"
            markdown = root / "minimal-edits.md"
            build_fixture(source)
            packets = extract_page_packets(source)

            edit = DirectEdit(
                edit_id="DME-00001",
                packet_id=packets[0].packet_id,
                pdf_page_index=0,
                original_text="能够有效提升",
                occurrence_index=0,
                corrected_text="有助于提升",
                category="wording",
                reason="表达空泛",
                rects=locate_text(packets[0], "能够有效提升"),
            )
            mark_one = ConsistencyMark(
                mark_id="LCM-00001",
                cluster_id="LCC-0001",
                packet_id=packets[0].packet_id,
                pdf_page_index=0,
                original_text="采访者",
                occurrence_index=0,
                rects=locate_text(packets[0], "采访者"),
            )
            mark_two = ConsistencyMark(
                mark_id="LCM-00002",
                cluster_id="LCC-0001",
                packet_id=packets[1].packet_id,
                pdf_page_index=1,
                original_text="企业知识管理顾问",
                occurrence_index=0,
                rects=locate_text(packets[1], "企业知识管理顾问"),
            )

            render_minimal_pdf(source, output, [edit], [mark_one, mark_two])
            write_minimal_markdown(markdown, [edit])

            reader = PdfReader(str(output))
            self.assertEqual(len(reader.pages), 2)
            annotations = [
                reference.get_object()
                for page in reader.pages
                for reference in page.get("/Annots", [])
            ]
            red = next(item for item in annotations if item.get("/Subtype") == "/Underline")
            self.assertEqual(red.get("/Contents"), "修改为：有助于提升")
            yellow = [
                item
                for item in annotations
                if str(item.get("/NM", "")).startswith("LCM-")
            ]
            self.assertEqual(len(yellow), 2)
            self.assertTrue(all(item.get("/Subtype") == "/Highlight" for item in yellow))
            self.assertTrue(all("/Contents" not in item and "/T" not in item for item in yellow))
            self.assertEqual(
                markdown.read_text(encoding="utf-8").splitlines(),
                [
                    "| 页码 | 原句 | 修改 |",
                    "|---|---|---|",
                    "| PDF 1 | 能够有效提升 | 有助于提升 |",
                ],
            )

    def test_overlapping_consistency_clusters_merge(self) -> None:
        shared = ConsistencyOccurrenceDraft(
            packet_id="AMR-P0002",
            pdf_page_index=1,
            original_text="专业采访者",
        )
        reviews = [
            ConsistencyWindowReview(
                window_id="CW-1",
                clusters=[
                    ConsistencyClusterDraft(
                        object_summary="访谈角色",
                        relation_type="role_granularity_shift",
                        occurrences=[
                            ConsistencyOccurrenceDraft(
                                packet_id="AMR-P0001",
                                pdf_page_index=0,
                                original_text="采访者",
                            ),
                            shared,
                        ],
                    )
                ],
            ),
            ConsistencyWindowReview(
                window_id="CW-2",
                clusters=[
                    ConsistencyClusterDraft(
                        object_summary="AI访谈角色",
                        relation_type="same_referent_label_drift",
                        occurrences=[
                            shared,
                            ConsistencyOccurrenceDraft(
                                packet_id="AMR-P0003",
                                pdf_page_index=2,
                                original_text="企业知识管理顾问",
                            ),
                        ],
                    )
                ],
            ),
        ]

        clusters = consolidate_clusters(reviews)

        self.assertEqual(len(clusters), 1)
        self.assertEqual(len(clusters[0].occurrences), 3)

    def test_page_spec(self) -> None:
        self.assertEqual(parse_pages("1-3,5", 6), [0, 1, 2, 4])
        with self.assertRaises(ValueError):
            parse_pages("4-2", 6)

    def test_consistency_is_opt_in(self) -> None:
        parser = build_parser()
        default_args = parser.parse_args(["source.pdf", "--output-dir", "output"])
        enabled_args = parser.parse_args(
            [
                "source.pdf",
                "--output-dir",
                "output",
                "--include-consistency",
            ]
        )

        self.assertFalse(default_args.include_consistency)
        self.assertTrue(enabled_args.include_consistency)

    def test_default_review_run_skips_consistency_model_calls(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.pdf"
            build_fixture(source)
            packets = extract_page_packets(source)

            class FakeReviewer:
                consistency_calls = 0

                def __init__(self, **kwargs) -> None:
                    pass

                async def __aenter__(self):
                    return self

                async def __aexit__(self, exc_type, exc, traceback) -> None:
                    pass

                async def direct(self, batch):
                    return (
                        DirectBatchReview(
                            batch_id=batch.batch_id,
                            reviews=[
                                DirectPageReview(
                                    packet_id=packet_id,
                                    pdf_page_index=next(
                                        packet.pdf_page_index
                                        for packet in batch.packets
                                        if packet.packet_id == packet_id
                                    ),
                                    edits=[],
                                )
                                for packet_id in batch.core_packet_ids
                            ],
                        ),
                        {},
                    )

                async def consistency(self, window):
                    FakeReviewer.consistency_calls += 1
                    return (
                        ConsistencyWindowReview(
                            window_id=window.window_id,
                            clusters=[],
                        ),
                        {},
                    )

            with patch(
                "ai_manuscript_repair.review.CodexReviewer", FakeReviewer
            ):
                direct, consistency = asyncio.run(
                    run_reviews(packets, root / "run-output")
                )

            self.assertEqual(len(direct), 1)
            self.assertEqual(consistency, [])
            self.assertEqual(FakeReviewer.consistency_calls, 0)


if __name__ == "__main__":
    unittest.main()
