"""Bounded exact-version arXiv HTML/PDF/abstract source acquisition."""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.request import Request, urlopen

from arxiv_triage.models import PaperIdentity, SourcePacket, sha256_bytes
from arxiv_triage.storage import ArtifactStore

from .source_fetch import freeze_source_packet


class SourceAcquisitionError(RuntimeError):
    pass


class ByteFetcher(Protocol):
    def fetch(self, url: str, *, timeout_seconds: int, max_bytes: int) -> bytes: ...


class PdfTextExtractor(Protocol):
    def extract(self, pdf_bytes: bytes, *, timeout_seconds: int) -> str: ...


class UrlLibFetcher:
    def fetch(self, url: str, *, timeout_seconds: int, max_bytes: int) -> bytes:
        request = Request(url, headers={"User-Agent": "arxiv-triage/0.1"})
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            data = response.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise SourceAcquisitionError("source response exceeds max_bytes")
        if not data:
            raise SourceAcquisitionError("source response is empty")
        return data


class PdftotextExtractor:
    def extract(self, pdf_bytes: bytes, *, timeout_seconds: int) -> str:
        with tempfile.TemporaryDirectory(prefix="arxiv-triage-pdf-") as directory:
            root = Path(directory) # root directory for source and output
            source = root / "source.pdf" 
            output = root / "source.txt"
            source.write_bytes(pdf_bytes) # writing the pdf data directly into a stored source file for our records. 
            completed = subprocess.run( # spawn subprocess to utilize cli tool to convert pdf bytes to text
                ["pdftotext", "-layout", str(source), str(output)],
                check=False,
                capture_output=True,
                timeout=timeout_seconds,
            )
            if completed.returncode != 0: # return code should be 0, if not, something happened.  We check what happened here.  
                detail = completed.stderr.decode("utf-8", errors="replace").strip()
                raise SourceAcquisitionError(f"pdftotext failed: {detail or completed.returncode}")
            text = output.read_text(encoding="utf-8")
            if not text.strip():
                raise SourceAcquisitionError("PDF extraction produced empty text")
            return text


@dataclass(frozen=True, slots=True)
class AcquiredSource:
    packet: SourcePacket
    normalized_text: str
    warnings: tuple[str, ...]


def _arxiv_id(identity: PaperIdentity) -> str:
    """Filters for arxiv id"""
    values = [item.value for item in identity.identifiers if item.scheme == "arxiv"]
    if len(values) != 1:
        raise SourceAcquisitionError("source acquisition requires exactly one arXiv identifier")
    return values[0]


def _preserve_failed_bytes(
    store: ArtifactStore, paper_id: str, kind: str, data: bytes
) -> str:
    digest = sha256_bytes(data)
    suffix = "html" if kind == "html" else "pdf"
    path = f"data/papers/{paper_id}/acquisition/{kind}-{digest}.{suffix}"
    store.write_bytes(path, data)
    return path


def acquire_arxiv_source(
    *,
    store: ArtifactStore,
    paper_identity: PaperIdentity,
    abstract: str | None,
    retrieved_at: str,
    fetcher: ByteFetcher | None = None,
    pdf_extractor: PdfTextExtractor | None = None,
    timeout_seconds: int = 30,
    max_bytes: int = 25_000_000,
) -> AcquiredSource:
    """Attempt exact-version HTML, then PDF, then an explicit abstract packet."""

    if isinstance(timeout_seconds, bool) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if isinstance(max_bytes, bool) or max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    fetcher = fetcher or UrlLibFetcher() # allows test shim, create real fetcher if no fetcher provided
    pdf_extractor = pdf_extractor or PdftotextExtractor() # allows test shim, create real pdfextractor if none provided
    arxiv_id = _arxiv_id(paper_identity) # convert
    html_url = f"https://arxiv.org/html/{arxiv_id}"
    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    warnings: list[str] = []

    html_bytes: bytes | None = None
    try:
        html_bytes = fetcher.fetch(
            html_url, timeout_seconds=timeout_seconds, max_bytes=max_bytes
        )
        packet, text = freeze_source_packet(
            store=store,
            paper_identity=paper_identity,
            source_format="html",
            original_bytes=html_bytes,
            retrieved_at=retrieved_at,
            retrieval_method="direct",
            source_url=html_url,
            warnings=warnings,
        )
        return AcquiredSource(packet, text, tuple(warnings))
    except Exception as exc:
        if html_bytes:
            path = _preserve_failed_bytes(store, paper_identity.paper_id, "html", html_bytes)
            warnings.append(f"HTML rejected and preserved at {path}: {type(exc).__name__}: {exc}")
        else:
            warnings.append(f"HTML unavailable: {type(exc).__name__}: {exc}")

    pdf_bytes: bytes | None = None
    try:
        pdf_bytes = fetcher.fetch(
            pdf_url, timeout_seconds=timeout_seconds, max_bytes=max_bytes
        )
        extracted = pdf_extractor.extract(pdf_bytes, timeout_seconds=timeout_seconds)
        packet, text = freeze_source_packet(
            store=store,
            paper_identity=paper_identity,
            source_format="pdf_text",
            original_bytes=pdf_bytes,
            extracted_text=extracted,
            retrieved_at=retrieved_at,
            retrieval_method="fallback",
            source_url=pdf_url,
            warnings=warnings,
        )
        return AcquiredSource(packet, text, tuple(warnings))
    except Exception as exc:
        if pdf_bytes:
            path = _preserve_failed_bytes(store, paper_identity.paper_id, "pdf", pdf_bytes)
            warnings.append(f"PDF rejected and preserved at {path}: {type(exc).__name__}: {exc}")
        else:
            warnings.append(f"PDF unavailable: {type(exc).__name__}: {exc}")

    if abstract is None or not abstract.strip():
        raise SourceAcquisitionError("full-text routes failed and no frozen abstract is available")
    packet, text = freeze_source_packet(
        store=store,
        paper_identity=paper_identity,
        source_format="abstract",
        original_bytes=abstract.encode("utf-8"),
        retrieved_at=retrieved_at,
        retrieval_method="fallback",
        source_url=next(
            (item.url for item in paper_identity.identifiers if item.scheme == "arxiv"),
            None,
        ),
        warnings=warnings,
    )
    return AcquiredSource(packet, text, tuple(warnings))


def acquire_pdf_source(
    *,
    store: ArtifactStore,
    paper_identity: PaperIdentity,
    source_url: str,
    retrieved_at: str,
    fetcher: ByteFetcher | None = None,
    pdf_extractor: PdfTextExtractor | None = None,
    timeout_seconds: int = 30,
    max_bytes: int = 25_000_000,
) -> AcquiredSource:
    """Fetch and freeze one exact PDF already bound to a resolved identity.

    Workshop proceedings and venue sources are not necessarily mirrored on
    arXiv.  This route deliberately does no searching: the URL must already be
    present on the exact ``PaperIdentity`` supplied by the deterministic
    resolver.
    """

    if paper_identity.identity_status != "resolved_exact":
        raise SourceAcquisitionError("PDF acquisition requires a resolved-exact identity")
    if not any(identifier.url == source_url for identifier in paper_identity.identifiers):
        raise SourceAcquisitionError("PDF URL is not bound to the supplied paper identity")
    if isinstance(timeout_seconds, bool) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if isinstance(max_bytes, bool) or max_bytes <= 0:
        raise ValueError("max_bytes must be positive")

    fetcher = fetcher or UrlLibFetcher()
    pdf_extractor = pdf_extractor or PdftotextExtractor()
    pdf_bytes: bytes | None = None
    try:
        pdf_bytes = fetcher.fetch(
            source_url, timeout_seconds=timeout_seconds, max_bytes=max_bytes
        )
        return freeze_pdf_source(
            store=store,
            paper_identity=paper_identity,
            source_url=source_url,
            pdf_bytes=pdf_bytes,
            retrieved_at=retrieved_at,
            pdf_extractor=pdf_extractor,
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:
        if pdf_bytes:
            path = _preserve_failed_bytes(
                store, paper_identity.paper_id, "pdf", pdf_bytes
            )
            detail = f"; response preserved at {path}"
        else:
            detail = ""
        raise SourceAcquisitionError(
            f"exact PDF acquisition failed: {type(exc).__name__}: {exc}{detail}"
        ) from exc


def freeze_pdf_source(
    *,
    store: ArtifactStore,
    paper_identity: PaperIdentity,
    source_url: str,
    pdf_bytes: bytes,
    retrieved_at: str,
    pdf_extractor: PdfTextExtractor | None = None,
    timeout_seconds: int = 30,
) -> AcquiredSource:
    """Freeze already-downloaded exact PDF bytes bound to one identity."""

    if paper_identity.identity_status != "resolved_exact":
        raise SourceAcquisitionError("PDF acquisition requires a resolved-exact identity")
    if not any(identifier.url == source_url for identifier in paper_identity.identifiers):
        raise SourceAcquisitionError("PDF URL is not bound to the supplied paper identity")
    if not pdf_bytes:
        raise SourceAcquisitionError("PDF response is empty")
    if isinstance(timeout_seconds, bool) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    pdf_extractor = pdf_extractor or PdftotextExtractor()
    extracted = pdf_extractor.extract(pdf_bytes, timeout_seconds=timeout_seconds)
    packet, text = freeze_source_packet(
        store=store,
        paper_identity=paper_identity,
        source_format="pdf_text",
        original_bytes=pdf_bytes,
        extracted_text=extracted,
        retrieved_at=retrieved_at,
        retrieval_method="direct",
        source_url=source_url,
    )
    return AcquiredSource(packet, text, ())


__all__ = [
    "AcquiredSource",
    "ByteFetcher",
    "PdfTextExtractor",
    "PdftotextExtractor",
    "SourceAcquisitionError",
    "UrlLibFetcher",
    "acquire_arxiv_source",
    "acquire_pdf_source",
    "freeze_pdf_source",
]
