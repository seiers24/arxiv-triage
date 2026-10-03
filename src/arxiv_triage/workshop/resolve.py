"""Deterministic workshop paper-identity resolution and Core adaptation."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from typing import Iterable

from arxiv_triage.models import (
    CandidatePaper,
    CandidateSet,
    PaperIdentity,
    sha256_json,
)

from .models import WorkshopCorpusManifest, WorkshopEntry


_SPACE = re.compile(r"\s+")


def normalized_title(value: str) -> str:
    """Normalize Unicode, dash variants, case, and whitespace without fuzzy matching."""

    value = unicodedata.normalize("NFKC", value)
    value = value.translate(str.maketrans({"–": "-", "—": "-", "−": "-"}))
    return _SPACE.sub(" ", value).strip().casefold()


def normalized_author(value: str) -> str:
    return _SPACE.sub(" ", unicodedata.normalize("NFKC", value)).strip().casefold()


def resolve_exact_titles(
    manifest: WorkshopCorpusManifest,
    identities: Iterable[PaperIdentity],
) -> WorkshopCorpusManifest:
    """Resolve unique exact normalized-title matches; keep ambiguity visible."""

    candidates: dict[str, list[PaperIdentity]] = defaultdict(list)
    for identity in identities:
        candidates[normalized_title(identity.title)].append(identity)

    resolved_entries: list[WorkshopEntry] = []
    for entry in manifest.entries:
        matches = candidates.get(normalized_title(entry.displayed_title), [])
        method: str | None = None
        confidence: str | None = None
        status: str
        paper_id: str | None = None
        reason: str | None
        if len(matches) == 1:
            match = matches[0]
            if match.identity_status != "resolved_exact":
                raise ValueError("automatic workshop resolution requires resolved-exact identity")
            status = "resolved_exact"
            method = "exact_normalized_title"
            confidence = "exact"
            paper_id = match.paper_id
            reason = None
        elif len(matches) > 1:
            listed_authors = {normalized_author(author) for author in entry.authors}
            narrowed = [
                match
                for match in matches
                if listed_authors.intersection(
                    normalized_author(author) for author in match.authors
                )
            ]
            if len(narrowed) == 1 and narrowed[0].identity_status == "resolved_exact":
                status = "resolved_exact"
                method = "exact_normalized_title_with_author_confirmation"
                confidence = "exact"
                paper_id = narrowed[0].paper_id
                reason = None
            else:
                status = "ambiguous"
                reason = "Multiple exact normalized-title candidates require human review"
        else:
            status = "not_found"
            reason = "No exact normalized-title identity was supplied"
        payload = entry.model_dump(mode="json")
        payload.update(
            {
                "paper_id": paper_id,
                "resolution_method": method,
                "resolution_confidence": confidence,
                "resolution_status": status,
                "human_review_reason": reason,
            }
        )
        payload["entry_hash"] = sha256_json(
            {key: value for key, value in payload.items() if key != "entry_hash"}
        )
        resolved_entries.append(WorkshopEntry.model_validate(payload))

    resolved_count = sum(
        entry.resolution_status == "resolved_exact" for entry in resolved_entries
    )
    payload = manifest.model_dump(mode="json")
    payload["entries"] = [entry.model_dump(mode="json") for entry in resolved_entries]
    payload["accounting"] = {
        "declared": manifest.accounting.declared,
        "extracted": manifest.accounting.extracted,
        "resolved": resolved_count,
        "identity_unresolved": manifest.accounting.extracted - resolved_count,
    }
    payload["manifest_hash"] = sha256_json(
        {key: value for key, value in payload.items() if key != "manifest_hash"}
    )
    return WorkshopCorpusManifest.model_validate(payload)


def candidate_set_from_workshop(
    *,
    investigation_id: str,
    search_plan_hash: str,
    manifest: WorkshopCorpusManifest,
    identities: Iterable[PaperIdentity],
    abstracts: dict[str, str | None],
    frozen_at: str,
) -> CandidateSet:
    """Adapt every authoritative listing entry into the complete Core corpus."""

    identity_by_id = {identity.paper_id: identity for identity in identities}
    candidates: list[CandidatePaper] = []
    for entry in manifest.entries:
        if entry.paper_id is not None:
            identity = identity_by_id[entry.paper_id]
            abstract = abstracts.get(identity.paper_id)
        else:
            paper_id = f"paper-{sha256_json({'title': normalized_title(entry.displayed_title)})[:16]}"
            identity_payload = {
                "schema_version": "2.0",
                "paper_id": paper_id,
                "title": entry.displayed_title,
                "authors": entry.authors,
                "published": None,
                "identifiers": [],
                "identity_status": "unresolved",
            }
            identity_payload["identity_hash"] = sha256_json(identity_payload)
            identity = PaperIdentity.model_validate(identity_payload)
            abstract = None
        candidate_payload = {
            "schema_version": "2.0",
            "paper_identity": identity.model_dump(mode="json"),
            "abstract": abstract,
            "discovery_refs": [entry.entry_id],
        }
        candidate_payload["candidate_hash"] = sha256_json(candidate_payload)
        candidates.append(CandidatePaper.model_validate(candidate_payload))
    payload = {
        "schema_version": "2.0",
        "investigation_id": investigation_id,
        "search_plan_hash": search_plan_hash,
        "discovery_ledger_hash": manifest.response_sha256,
        "frozen_at": frozen_at,
        "candidates": [candidate.model_dump(mode="json") for candidate in candidates],
    }
    payload["candidate_set_hash"] = sha256_json(payload)
    return CandidateSet.model_validate(payload)


__all__ = [
    "candidate_set_from_workshop",
    "normalized_author",
    "normalized_title",
    "resolve_exact_titles",
]
