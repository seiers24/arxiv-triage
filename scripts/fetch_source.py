#!/usr/bin/env python3
"""Acquire and freeze one exact-version arXiv source packet."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arxiv_triage.acquisition import (  # noqa: E402
    acquire_arxiv_source,
    acquire_pdf_source,
    freeze_pdf_source,
)
from arxiv_triage.models import CandidatePaper, PaperIdentity  # noqa: E402
from arxiv_triage.storage import ArtifactStore  # noqa: E402


def load_source(path: Path) -> tuple[PaperIdentity, str | None]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if "paper_identity" in value:
        candidate = CandidatePaper.model_validate(value)
        return candidate.paper_identity, candidate.abstract
    return PaperIdentity.model_validate(value), None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="CandidatePaper or PaperIdentity JSON")
    parser.add_argument("--abstract", help="frozen abstract when source is PaperIdentity")
    parser.add_argument(
        "--pdf-url",
        help="exact PDF URL already bound to the PaperIdentity; bypasses arXiv routing",
    )
    parser.add_argument(
        "--pdf-file",
        type=Path,
        help="already-downloaded exact PDF bytes; requires --pdf-url",
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--max-bytes", type=int, default=25_000_000)
    args = parser.parse_args(argv)
    try:
        identity, candidate_abstract = load_source(args.source)
        retrieved_at = datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ).replace("+00:00", "Z")
        common = {
            "store": ArtifactStore(args.root),
            "paper_identity": identity,
            "retrieved_at": retrieved_at,
            "timeout_seconds": args.timeout,
        }
        if args.pdf_file is not None and args.pdf_url is None:
            raise ValueError("--pdf-file requires --pdf-url")
        if args.pdf_file is not None:
            acquired = freeze_pdf_source(
                source_url=args.pdf_url,
                pdf_bytes=args.pdf_file.read_bytes(),
                **common,
            )
        elif args.pdf_url is not None:
            acquired = acquire_pdf_source(
                source_url=args.pdf_url, max_bytes=args.max_bytes, **common
            )
        else:
            acquired = acquire_arxiv_source(
                abstract=args.abstract if args.abstract is not None else candidate_abstract,
                max_bytes=args.max_bytes,
                **common,
            )
    except Exception as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "paper_id": identity.paper_id,
                "source_document_id": acquired.packet.source_document_id,
                "format": acquired.packet.format,
                "packet_path": (
                    f"data/papers/{identity.paper_id}/sources/"
                    f"{acquired.packet.source_document_id}/source-packet.json"
                ),
                "warnings": list(acquired.warnings),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
