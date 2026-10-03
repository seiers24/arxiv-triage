from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from arxiv_triage.acquisition import freeze_source_packet
from arxiv_triage.models import PaperIdentity, sha256_bytes, sha256_json
from arxiv_triage.storage import ArtifactStore
from arxiv_triage.workshop import (
    WorkshopSpec,
    candidate_set_from_workshop,
    parse_cvf_proceedings_pages,
    parse_known_workshop_url,
    resolve_exact_titles,
)


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/workshop"


def workshop_spec() -> WorkshopSpec:
    payload = {
        "schema_version": "2.0",
        "workshop_id": "edge-cvpr-2026",
        "name": "Third Workshop on Efficient and On-Device Generation",
        "ordinal": 3,
        "venue": "CVPR",
        "year": 2026,
        "dates": ["2026-06-03"],
        "authoritative_url": "https://cvpr26-edge.github.io/",
        "requested_population": "accepted",
        "tracks": [
            {"track_id": "long", "name": "Long Papers", "proceedings_included": True},
            {"track_id": "short", "name": "Short Papers", "proceedings_included": False},
        ],
        "source_precedence": ["authoritative_program", "openreview", "arxiv"],
    }
    payload["spec_hash"] = sha256_json(payload)
    return WorkshopSpec.model_validate(payload)


def extracted_manifest():
    golden = json.loads((FIXTURES / "edge-2026-accepted.json").read_text(encoding="utf-8"))
    return parse_known_workshop_url(
        spec=workshop_spec(),
        response_bytes=(FIXTURES / "edge-2026.html").read_bytes(),
        response_path="tests/fixtures/workshop/edge-2026.html",
        retrieved_at="2026-09-13T23:00:00Z",
        declared_count=golden["declared_count"],
    )


def resolved_identity(number: int, title: str, authors: list[str]) -> PaperIdentity:
    payload = {
        "schema_version": "2.0",
        "paper_id": f"edge-paper-{number:02d}",
        "title": title,
        "authors": authors,
        "published": None,
        "identifiers": [],
        "identity_status": "resolved_exact",
    }
    payload["identity_hash"] = sha256_json(payload)
    return PaperIdentity.model_validate(payload)


def test_edge_known_url_recovers_exact_manually_verified_population() -> None:
    golden = json.loads((FIXTURES / "edge-2026-accepted.json").read_text(encoding="utf-8"))
    response = (FIXTURES / "edge-2026.html").read_bytes()
    assert sha256_bytes(response) == golden["response_sha256"]
    manifest = parse_known_workshop_url(
        spec=workshop_spec(),
        response_bytes=response,
        response_path="tests/fixtures/workshop/edge-2026.html",
        retrieved_at="2026-09-13T23:00:00Z",
        declared_count=golden["declared_count"],
    )
    actual = [
        {
            "title": entry.displayed_title,
            "authors": entry.authors,
            "track_id": entry.track_id,
            "poster_number": entry.poster_number,
        }
        for entry in manifest.entries
    ]
    assert actual == golden["entries"]
    assert manifest.accounting.declared == manifest.accounting.extracted == 15
    assert sum(entry.track_id == "long" for entry in manifest.entries) == 10
    assert sum(entry.track_id == "short" for entry in manifest.entries) == 5
    assert len({entry.displayed_title for entry in manifest.entries}) == 15
    assert manifest.completeness_status == "complete"
    assert manifest.excluded_nonpaper_items == [
        "speakers",
        "schedule talks",
        "organizers",
        "sponsors",
        "navigation links",
    ]
    assert manifest.warnings == [
        "Authoritative accepted section says Second Workshop; frozen spec says Third Workshop"
    ]

    source_text = response.decode("utf-8")
    for entry in manifest.entries:
        entry.listing_span.validate_against(source_text, manifest.response_sha256)
        assert entry.displayed_title in entry.listing_span.quote
        assert all(author in entry.listing_span.quote for author in entry.authors)


def test_edge_extractor_rejects_unbounded_or_incomplete_pages() -> None:
    response = (FIXTURES / "edge-2026.html").read_bytes()
    with pytest.raises(ValueError, match="bounded accepted-paper section"):
        parse_known_workshop_url(
            spec=workshop_spec(),
            response_bytes=response.replace(b'id="organizers"', b'id="people"'),
            response_path="tests/fixtures/workshop/changed.html",
            retrieved_at="2026-09-13T23:00:00Z",
            declared_count=15,
        )

    incomplete = response.replace(
        b"<strong>Title:</strong> ELT: Elastic Looped Transformers for Visual Generation",
        b"<strong>Heading:</strong> ELT: Elastic Looped Transformers for Visual Generation",
    )
    with pytest.raises(ValueError, match="lacks title"):
        parse_known_workshop_url(
            spec=workshop_spec(),
            response_bytes=incomplete,
            response_path="tests/fixtures/workshop/changed.html",
            retrieved_at="2026-09-13T23:00:00Z",
            declared_count=15,
        )


def test_workshop_cli_freezes_known_url_fixture(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    spec_path = tmp_path / "workshop-spec-input.json"
    spec_path.write_text(workshop_spec().model_dump_json(), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(repository_root / "scripts/workshop.py"),
            "--root",
            str(tmp_path),
            "extract-known-url",
            "--spec",
            str(spec_path),
            "--declared-count",
            "15",
            "--response",
            str(FIXTURES / "edge-2026.html"),
            "--retrieved-at",
            "2026-09-13T23:00:00Z",
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["extracted"] == 15
    assert (
        tmp_path / "data/workshops/edge-cvpr-2026/accepted-corpus.json"
    ).is_file()


def test_exact_resolution_and_core_adapter_preserve_all_fifteen_entries() -> None:
    manifest = extracted_manifest()
    identities = [
        resolved_identity(entry.ordinal, entry.displayed_title, entry.authors)
        for entry in manifest.entries
    ]
    resolved = resolve_exact_titles(manifest, reversed(identities))
    assert resolved.accounting.resolved == 15
    assert resolved.accounting.identity_unresolved == 0
    assert all(entry.resolution_status == "resolved_exact" for entry in resolved.entries)

    candidates = candidate_set_from_workshop(
        investigation_id="inv-edge-2026",
        search_plan_hash="a" * 64,
        manifest=resolved,
        identities=identities,
        abstracts={identity.paper_id: None for identity in identities},
        frozen_at="2026-09-13T23:10:00Z",
    )
    assert len(candidates.candidates) == 15
    assert [candidate.discovery_refs for candidate in candidates.candidates] == [
        [f"workshop-entry-{number:04d}"] for number in range(1, 16)
    ]


def test_title_collision_requires_author_confirmation_or_human_review() -> None:
    manifest = extracted_manifest()
    first = manifest.entries[0]
    exact = resolved_identity(1, first.displayed_title, first.authors)
    collision = resolved_identity(2, first.displayed_title, ["Different Author"])
    resolved = resolve_exact_titles(manifest, [collision, exact])
    assert resolved.entries[0].resolution_status == "resolved_exact"
    assert "author_confirmation" in resolved.entries[0].resolution_method

    ambiguous = resolve_exact_titles(
        manifest,
        [exact, resolved_identity(3, first.displayed_title, first.authors)],
    )
    assert ambiguous.entries[0].resolution_status == "ambiguous"
    assert ambiguous.entries[0].human_review_reason


def test_cvf_proceedings_resolve_the_nine_published_long_papers_exactly() -> None:
    pages = [
        (
            "https://openaccess.thecvf.com/CVPR2026_workshops/EDGE",
            (FIXTURES / "cvpr2026-edge-proceedings.html").read_bytes(),
        ),
        (
            "https://openaccess.thecvf.com/CVPR2026_workshops/EGDE",
            (FIXTURES / "cvpr2026-egde-proceedings.html").read_bytes(),
        ),
    ]
    assert sha256_bytes(pages[0][1]) == (
        "1a706af925ed398d4ac99e7acd53487637452ad9e1dc1cbff3eb86dd4331efd0"
    )
    assert sha256_bytes(pages[1][1]) == (
        "17a28284996a4f1e595937851bb5cbe07b8b5561658a45577d92c346051644d4"
    )
    identities = parse_cvf_proceedings_pages(pages)
    assert len(identities) == 9
    assert all(identity.identity_status == "resolved_exact" for identity in identities)
    assert all(
        identity.identifiers[0].scheme == "proceedings"
        and identity.identifiers[0].url.endswith("_paper.pdf")
        for identity in identities
    )
    assert {identity.title for identity in identities}.issubset(
        {entry.displayed_title.replace("–", "-") for entry in extracted_manifest().entries}
    )

    resolved = resolve_exact_titles(extracted_manifest(), identities)
    assert resolved.accounting.resolved == 9
    assert sum(
        entry.resolution_status == "not_found" for entry in resolved.entries
    ) == 6


def test_workshop_cli_freezes_cvf_resolution_without_overwriting_extraction(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    manifest_path = tmp_path / "accepted-input.json"
    manifest_path.write_text(extracted_manifest().model_dump_json(), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(repository_root / "scripts/workshop.py"),
            "--root",
            str(tmp_path),
            "resolve-cvf",
            "--workshop-id",
            "edge-cvpr-2026",
            "--manifest",
            str(manifest_path),
            "--page",
            "https://openaccess.thecvf.com/CVPR2026_workshops/EDGE",
            str(FIXTURES / "cvpr2026-edge-proceedings.html"),
            "--page",
            "https://openaccess.thecvf.com/CVPR2026_workshops/EGDE",
            str(FIXTURES / "cvpr2026-egde-proceedings.html"),
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["resolved"] == 9
    assert payload["unresolved"] == 6
    resolved_path = tmp_path / payload["manifest_path"]
    assert resolved_path.is_file()
    assert not (tmp_path / "data/workshops/edge-cvpr-2026/accepted-corpus.json").exists()
    assert len(list((tmp_path / "data/papers").glob("*/identity.json"))) == 9


def test_cvf_and_curated_primary_identities_resolve_all_fifteen() -> None:
    pages = [
        (
            "https://openaccess.thecvf.com/CVPR2026_workshops/EDGE",
            (FIXTURES / "cvpr2026-edge-proceedings.html").read_bytes(),
        ),
        (
            "https://openaccess.thecvf.com/CVPR2026_workshops/EGDE",
            (FIXTURES / "cvpr2026-egde-proceedings.html").read_bytes(),
        ),
    ]
    identities = parse_cvf_proceedings_pages(pages)
    identities.extend(
        PaperIdentity.model_validate(item)
        for item in json.loads(
            (FIXTURES / "edge-2026-external-identities.json").read_text(
                encoding="utf-8"
            )
        )
    )
    resolved = resolve_exact_titles(extracted_manifest(), identities)
    assert len(identities) == 15
    assert resolved.accounting.resolved == 15
    assert resolved.accounting.identity_unresolved == 0
    assert all(entry.resolution_status == "resolved_exact" for entry in resolved.entries)


def test_source_reconciliation_validates_all_frozen_bytes_and_preserves_attempt(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    manifest = extracted_manifest()
    identities = [
        resolved_identity(entry.ordinal, entry.displayed_title, entry.authors)
        for entry in manifest.entries
    ]
    manifest = resolve_exact_titles(manifest, identities)
    store = ArtifactStore(tmp_path)
    for identity in identities:
        store.write_json(f"data/papers/{identity.paper_id}/identity.json", identity)
        freeze_source_packet(
            store=store,
            paper_identity=identity,
            source_format="abstract",
            original_bytes=f"Frozen source for {identity.title}".encode(),
            retrieved_at="2026-09-14T20:00:00Z",
            retrieval_method="fallback",
            source_url=None,
        )
    manifest_path = tmp_path / "resolved-corpus.json"
    manifest_path.write_text(manifest.model_dump_json(), encoding="utf-8")
    acquisition: dict[str, object] = {
        "schema_version": "2.0",
        "workshop_id": "edge-cvpr-2026",
        "workshop_manifest_hash": manifest.manifest_hash,
        "retrieved_at": "2026-09-14T20:00:00Z",
        "max_concurrent": 4,
        "results": [],
    }
    acquisition["source_run_hash"] = sha256_json(acquisition)
    acquisition_path = tmp_path / "source-acquisition.json"
    acquisition_path.write_text(json.dumps(acquisition), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(repository_root / "scripts/workshop.py"),
            "--root",
            str(tmp_path),
            "reconcile-sources",
            "--workshop-id",
            "edge-cvpr-2026",
            "--manifest",
            str(manifest_path),
            "--acquisition",
            str(acquisition_path),
            "--reconciled-at",
            "2026-09-14T21:00:00Z",
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["expected"] == output["ready"] == 15
    readiness = json.loads(
        (tmp_path / output["source_readiness_path"]).read_text(encoding="utf-8")
    )
    assert readiness["acquisition_attempt"]["source_run_hash"] == acquisition["source_run_hash"]
    assert all(item["status"] == "ready" for item in readiness["results"])
