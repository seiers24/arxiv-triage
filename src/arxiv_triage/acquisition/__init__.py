"""Deterministic source acquisition and normalization primitives."""

from .normalize import NormalizedSource, normalize_html, normalize_plain_text
from .arxiv_source import (
    AcquiredSource,
    PdftotextExtractor,
    SourceAcquisitionError,
    UrlLibFetcher,
    acquire_arxiv_source,
    acquire_pdf_source,
    freeze_pdf_source,
)
from .source_fetch import freeze_source_packet

__all__ = [
    "NormalizedSource",
    "AcquiredSource",
    "PdftotextExtractor",
    "SourceAcquisitionError",
    "UrlLibFetcher",
    "acquire_arxiv_source",
    "acquire_pdf_source",
    "freeze_pdf_source",
    "freeze_source_packet",
    "normalize_html",
    "normalize_plain_text",
]
