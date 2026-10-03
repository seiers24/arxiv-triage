"""Freeze already-acquired source bytes as a validated ``SourcePacket``."""

from __future__ import annotations

from typing import Literal, Sequence

from arxiv_triage.models import PaperIdentity, SourcePacket, sha256_bytes, sha256_json
from arxiv_triage.storage import ArtifactStore

from .normalize import normalize_html, normalize_plain_text


SourceFormat = Literal["html", "pdf_text", "abstract"]
RetrievalMethod = Literal["direct", "fallback"]


def freeze_source_packet(
    *,
    store: ArtifactStore,
    paper_identity: PaperIdentity,
    source_format: SourceFormat,
    original_bytes: bytes,
    retrieved_at: str,
    retrieval_method: RetrievalMethod,
    source_url: str | None,
    warnings: Sequence[str] = (),
    extracted_text: str | None = None,
) -> tuple[SourcePacket, str]:
    """Normalize and immutably persist one source representation.

    For ``pdf_text``, callers may supply opaque PDF ``original_bytes`` plus the
    deterministic ``extracted_text``. Omitting it treats the original bytes as
    an already-extracted UTF-8 fixture.
    """

    if source_format == "html":
        normalized = normalize_html(original_bytes)
        extension = "html"
    elif source_format == "pdf_text" and extracted_text is not None:
        normalized = normalize_plain_text(extracted_text, heading="Document")
        extension = "pdf"
    else:
        try:
            decoded = original_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"{source_format} source must be valid UTF-8") from exc
        normalized = normalize_plain_text(
            decoded, heading="Abstract" if source_format == "abstract" else "Document"
        )
        extension = "txt"

    original_hash = sha256_bytes(original_bytes)
    normalized_hash = sha256_bytes(normalized.text.encode("utf-8"))
    document_seed = {
        "paper_id": paper_identity.paper_id,
        "format": source_format,
        "original_sha256": original_hash,
        "normalized_sha256": normalized_hash,
    }
    source_document_id = f"src-{sha256_json(document_seed)[:16]}"
    base = f"data/papers/{paper_identity.paper_id}/sources/{source_document_id}"
    original_path = f"{base}/original.{extension}"
    normalized_path = f"{base}/normalized.txt"
    packet_path = f"{base}/source-packet.json"

    store.write_bytes(original_path, original_bytes)
    store.write_text(normalized_path, normalized.text)
    packet_payload: dict[str, object] = {
        "schema_version": "2.0",
        "source_document_id": source_document_id,
        "paper_id": paper_identity.paper_id,
        "format": source_format,
        "retrieval_method": retrieval_method,
        "source_url": source_url,
        "retrieved_at": retrieved_at,
        "original_path": original_path,
        "original_sha256": original_hash,
        "normalized_path": normalized_path,
        "normalized_sha256": normalized_hash,
        "sections": [
            {
                "section_id": f"sec-{index:04d}",
                "heading": section.heading,
                "start_char": section.start_char,
                "end_char": section.end_char,
            }
            for index, section in enumerate(normalized.sections, start=1)
        ],
        "warnings": list(warnings),
    }
    packet_payload["packet_hash"] = sha256_json(packet_payload)
    packet = SourcePacket.model_validate(packet_payload)
    packet.validate_normalized_text(normalized.text)
    store.write_json(packet_path, packet)
    return packet, normalized.text


__all__ = ["RetrievalMethod", "SourceFormat", "freeze_source_packet"]
