"""Deterministic extraction of an authoritative workshop accepted-paper list."""

from __future__ import annotations

import html
import re
from typing import Any

from arxiv_triage.models import sha256_bytes, sha256_json

from .models import WorkshopCorpusManifest, WorkshopEntry, WorkshopSpec


_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_ACCEPTED = re.compile(
    r'<div\s+class="text-center"\s+id="accepted-papers">', re.IGNORECASE
)
_ORGANIZERS = re.compile(
    r'<div\s+class="text-center"\s+id="organizers">', re.IGNORECASE
)
_HEADING = re.compile(r"<h2>(.*?)</h2>", re.IGNORECASE | re.DOTALL)
_ITEM = re.compile(r"<li>(.*?)</li>", re.IGNORECASE | re.DOTALL)
_TITLE = re.compile(
    r"<strong>\s*Title:\s*</strong>\s*(.*?)<br\s*/?>",
    re.IGNORECASE | re.DOTALL,
)
_AUTHORS = re.compile(
    r"<strong>\s*Authors:\s*</strong>\s*(.*?)<br\s*/?>",
    re.IGNORECASE | re.DOTALL,
)
_POSTER = re.compile(r"\[\s*Poster\s*#(\d+)\s*\]", re.IGNORECASE)
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def _plain(fragment: str) -> str:
    return _SPACE.sub(" ", html.unescape(_TAG.sub("", fragment))).strip()


def parse_known_workshop_url(
    *,
    spec: WorkshopSpec,
    response_bytes: bytes,
    response_path: str,
    retrieved_at: str,
    declared_count: int,
) -> WorkshopCorpusManifest:
    """Extract only the accepted-paper section from one frozen response."""

    source_text = response_bytes.decode("utf-8")
    scan_text = _COMMENT.sub(
        lambda match: re.sub(r"[^\n]", " ", match.group(0)), source_text
    )
    response_hash = sha256_bytes(response_bytes)
    accepted_match = _ACCEPTED.search(scan_text)
    organizer_match = _ORGANIZERS.search(scan_text)
    if accepted_match is None or organizer_match is None:
        raise ValueError("authoritative page lacks bounded accepted-paper section")
    if organizer_match.start() <= accepted_match.end():
        raise ValueError("accepted-paper section boundaries are reversed")
    section_start = accepted_match.end()
    section_end = organizer_match.start()
    section = scan_text[section_start:section_end]
    headings = list(_HEADING.finditer(section))
    if [_plain(item.group(1)) for item in headings] != ["Long Papers", "Short Papers"]:
        raise ValueError("accepted-paper section must contain long then short tracks")

    entries: list[WorkshopEntry] = []
    for item in _ITEM.finditer(section):
        item_start = section_start + item.start()
        item_end = section_start + item.end()
        preceding = [heading for heading in headings if heading.start() < item.start()]
        if not preceding:
            raise ValueError("accepted paper appears before a track heading")
        track_name = _plain(preceding[-1].group(1))
        track_id = "long" if track_name == "Long Papers" else "short"
        original_item = source_text[item_start:item_end]
        title_match = _TITLE.search(original_item)
        authors_match = _AUTHORS.search(original_item)
        poster_match = _POSTER.search(original_item)
        if title_match is None or authors_match is None or poster_match is None:
            raise ValueError("accepted-paper item lacks title, authors, or poster number")
        title = _plain(title_match.group(1))
        authors = [part.strip() for part in _plain(authors_match.group(1)).split(",")]
        if any(not author for author in authors):
            raise ValueError("accepted-paper author list contains an empty author")
        payload: dict[str, Any] = {
            "schema_version": "2.0",
            "entry_id": f"workshop-entry-{len(entries) + 1:04d}",
            "ordinal": len(entries) + 1,
            "displayed_title": title,
            "authors": authors,
            "track_id": track_id,
            "poster_number": int(poster_match.group(1)),
            "acceptance_status": "accepted",
            "listing_span": {
                "response_sha256": response_hash,
                "start_char": item_start,
                "end_char": item_end,
                "quote": source_text[item_start:item_end],
            },
            "paper_id": None,
            "resolution_method": None,
            "resolution_confidence": None,
            "resolution_status": "unresolved",
            "human_review_reason": "Paper identity resolution has not run",
        }
        payload["entry_hash"] = sha256_json(payload)
        entry = WorkshopEntry.model_validate(payload)
        entry.listing_span.validate_against(source_text, response_hash)
        entries.append(entry)

    warning = "Authoritative accepted section says Second Workshop; frozen spec says Third Workshop"
    warnings = [warning] if "Second Workshop" in section else []
    request_hash = sha256_json(
        {"method": "GET", "url": spec.authoritative_url, "headers": {}}
    )
    accounting = {
        "declared": declared_count,
        "extracted": len(entries),
        "resolved": 0,
        "identity_unresolved": len(entries),
    }
    payload = {
        "schema_version": "2.0",
        "workshop_spec_hash": spec.spec_hash,
        "authoritative_url": spec.authoritative_url,
        "request_sha256": request_hash,
        "response_path": response_path,
        "response_sha256": response_hash,
        "retrieved_at": retrieved_at,
        "entries": [entry.model_dump(mode="json") for entry in entries],
        "excluded_nonpaper_items": [
            "speakers",
            "schedule talks",
            "organizers",
            "sponsors",
            "navigation links",
        ],
        "warnings": warnings,
        "accounting": accounting,
        "completeness_status": "complete" if len(entries) == declared_count else "incomplete",
    }
    payload["manifest_hash"] = sha256_json(payload)
    return WorkshopCorpusManifest.model_validate(payload)


__all__ = ["parse_known_workshop_url"]
