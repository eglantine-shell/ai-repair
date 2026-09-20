from __future__ import annotations

import argparse
import json
from pathlib import Path

from pypdf import PdfReader

from ai_manuscript_repair.pipeline import parse_pages, run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Minimally repair accepted Chinese AI manuscripts, with optional "
            "local semantic consistency highlighting."
        )
    )
    parser.add_argument("input_pdf", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--pages", help="1-based pages, e.g. 1-3,8")
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--reasoning-effort", default="medium")
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--context-pages", type=int, default=1)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument(
        "--include-consistency",
        action="store_true",
        help=(
            "also run the experimental local-consistency pass and add silent "
            "yellow highlights; disabled by default"
        ),
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not args.input_pdf.is_file():
        raise SystemExit(f"input PDF not found: {args.input_pdf}")
    page_count = len(PdfReader(str(args.input_pdf)).pages)
    try:
        page_indexes = parse_pages(args.pages, page_count)
        summary = run_pipeline(
            args.input_pdf,
            args.output_dir,
            page_indexes=page_indexes,
            model=args.model,
            reasoning_effort=args.reasoning_effort,
            concurrency=args.concurrency,
            batch_size=args.batch_size,
            context_pages=args.context_pages,
            retries=args.retries,
            include_consistency=args.include_consistency,
        )
    except Exception as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
