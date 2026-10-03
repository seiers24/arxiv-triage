#!/usr/bin/env python3
"""Deterministic workshop-analysis acquisition commands."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arxiv_triage.acquisition import (  # noqa: E402
    UrlLibFetcher,
    acquire_arxiv_source,
    acquire_pdf_source,
)
from arxiv_triage.models import (  # noqa: E402
    InvestigationSpec,
    PaperIdentity,
    ScreeningScope,
    SearchPlan,
    SourcePacket,
    sha256_bytes,
    sha256_json,
)
from arxiv_triage.storage import ArtifactStore  # noqa: E402
from arxiv_triage.workshop import (  # noqa: E402
    WorkshopCorpusManifest,
    WorkshopSpec,
    candidate_set_from_workshop,
    materialize_workshop_overlays,
    parse_cvf_proceedings_pages,
    parse_known_workshop_url,
    resolve_exact_titles,
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def cmd_extract_known_url(args: argparse.Namespace) -> dict[str, object]:
    spec = WorkshopSpec.model_validate_json(args.spec.read_bytes())
    response = (
        args.response.read_bytes()
        if args.response is not None
        else UrlLibFetcher().fetch(
            spec.authoritative_url,
            timeout_seconds=args.timeout,
            max_bytes=args.max_bytes,
        )
    )
    store = ArtifactStore(args.root)
    response_hash = sha256_bytes(response)
    response_path = (
        f"data/workshops/{spec.workshop_id}/sources/{response_hash}.html"
    )
    store.write_bytes(response_path, response)
    manifest = parse_known_workshop_url(
        spec=spec,
        response_bytes=response,
        response_path=response_path,
        retrieved_at=args.retrieved_at or now(),
        declared_count=args.declared_count,
    )
    spec_path = f"data/workshops/{spec.workshop_id}/workshop-spec.json"
    manifest_path = f"data/workshops/{spec.workshop_id}/accepted-corpus.json"
    store.write_json(spec_path, spec)
    store.write_json(manifest_path, manifest)
    return {
        "workshop_id": spec.workshop_id,
        "manifest_path": manifest_path,
        "response_sha256": response_hash,
        "extracted": manifest.accounting.extracted,
        "completeness_status": manifest.completeness_status,
    }


def cmd_resolve_cvf(args: argparse.Namespace) -> dict[str, object]:
    store = ArtifactStore(args.root)
    manifest = WorkshopCorpusManifest.model_validate_json(args.manifest.read_bytes())
    pages: list[tuple[str, bytes]] = []
    for page_url, page_path in args.page:
        response = Path(page_path).read_bytes()
        response_hash = sha256_bytes(response)
        store.write_bytes(
            f"data/workshops/{args.workshop_id}/sources/{response_hash}.html",
            response,
        )
        pages.append((page_url, response))
    identities = parse_cvf_proceedings_pages(pages)
    for path in args.identity:
        value = json.loads(path.read_text(encoding="utf-8"))
        values = value if isinstance(value, list) else [value]
        identities.extend(PaperIdentity.model_validate(item) for item in values)
    resolved = resolve_exact_titles(manifest, identities)
    for identity in identities:
        store.write_json(f"data/papers/{identity.paper_id}/identity.json", identity)
    manifest_path = f"data/workshops/{args.workshop_id}/resolved-corpus.json"
    store.write_json(manifest_path, resolved)
    return {
        "workshop_id": args.workshop_id,
        "manifest_path": manifest_path,
        "identity_count": len(identities),
        "resolved": resolved.accounting.resolved,
        "unresolved": resolved.accounting.declared - resolved.accounting.resolved,
    }


def cmd_materialize_overlays(args: argparse.Namespace) -> dict[str, object]:
    manifest, focus, critic, reviewer = materialize_workshop_overlays(args.skill_dir)
    skill_hash = manifest["skill_hash"]
    base = f"data/workshops/{args.workshop_id}/overlays/{skill_hash}"
    store = ArtifactStore(args.root)
    paths = {
        "manifest_path": f"{base}/manifest.json",
        "reader_focus_path": f"{base}/reader-focus.json",
        "critic_rubric_path": f"{base}/critic-rubric.json",
        "reviewer_rubric_path": f"{base}/reviewer-rubric.json",
    }
    for key, value in (
        ("manifest_path", manifest),
        ("reader_focus_path", focus),
        ("critic_rubric_path", critic),
        ("reviewer_rubric_path", reviewer),
    ):
        store.write_json(paths[key], value)
    return {"workshop_id": args.workshop_id, "skill_hash": skill_hash, **paths}


def cmd_build_core_inputs(args: argparse.Namespace) -> dict[str, object]:
    store = ArtifactStore(args.root)
    manifest = WorkshopCorpusManifest.model_validate_json(args.manifest.read_bytes())
    base = args.root / "data/investigations" / args.investigation_id
    investigation = InvestigationSpec.model_validate_json(
        (base / "investigation.json").read_bytes()
    )
    plan = SearchPlan.model_validate_json((base / "search-plan.json").read_bytes())
    if plan.component != "workshop-analysis":
        raise ValueError("frozen search plan is not a workshop-analysis component")
    if manifest.accounting.identity_unresolved:
        raise ValueError("cannot build Core inputs with unresolved workshop identities")
    identities = [
        PaperIdentity.model_validate_json(
            store.resolve(f"data/papers/{entry.paper_id}/identity.json").read_bytes()
        )
        for entry in manifest.entries
        if entry.paper_id is not None
    ]
    if len(identities) != manifest.accounting.declared:
        raise ValueError("resolved workshop identity count does not equal declared count")
    candidates = candidate_set_from_workshop(
        investigation_id=args.investigation_id,
        search_plan_hash=plan.search_plan_hash,
        manifest=manifest,
        identities=identities,
        abstracts={identity.paper_id: None for identity in identities},
        frozen_at=args.frozen_at,
    )
    if not all(isinstance(rule, str) for rule in plan.inclusion_rules):
        raise ValueError("workshop inclusion rules must be strings")
    if not all(isinstance(rule, str) for rule in plan.exclusion_rules):
        raise ValueError("workshop exclusion rules must be strings")
    scope_payload = {
        "schema_version": "2.0",
        "question": investigation.question,
        "inclusion_rules": plan.inclusion_rules,
        "exclusion_rules": plan.exclusion_rules,
    }
    scope_payload["scope_hash"] = sha256_json(scope_payload)
    scope = ScreeningScope.model_validate(scope_payload)
    component_base = f"data/workshops/{args.workshop_id}/core-inputs"
    candidate_path = f"{component_base}/candidates.json"
    scope_path = f"{component_base}/screening-scope.json"
    store.write_json(candidate_path, candidates)
    store.write_json(scope_path, scope)
    return {
        "workshop_id": args.workshop_id,
        "investigation_id": args.investigation_id,
        "candidate_path": candidate_path,
        "screening_scope_path": scope_path,
        "candidates": len(candidates.candidates),
    }


def cmd_fetch_sources(args: argparse.Namespace) -> dict[str, object]:
    if args.max_concurrent <= 0:
        raise ValueError("max-concurrent must be positive")
    store = ArtifactStore(args.root)
    manifest = WorkshopCorpusManifest.model_validate_json(args.manifest.read_bytes())
    identities = [
        PaperIdentity.model_validate_json(
            store.resolve(f"data/papers/{entry.paper_id}/identity.json").read_bytes()
        )
        for entry in manifest.entries
        if entry.paper_id is not None
    ]
    if len(identities) != manifest.accounting.resolved:
        raise ValueError("source fetch requires every resolved identity artifact")

    def acquire(identity: PaperIdentity) -> dict[str, object]:
        try:
            arxiv = [item for item in identity.identifiers if item.scheme == "arxiv"]
            if arxiv:
                result = acquire_arxiv_source(
                    store=store,
                    paper_identity=identity,
                    abstract=None,
                    retrieved_at=args.retrieved_at,
                    timeout_seconds=args.timeout,
                    max_bytes=args.max_bytes,
                )
            else:
                exact_pdfs = [
                    item
                    for scheme in ("proceedings", "openreview")
                    for item in identity.identifiers
                    if item.scheme == scheme
                ]
                if not exact_pdfs:
                    raise ValueError("identity has no supported exact full-text route")
                result = acquire_pdf_source(
                    store=store,
                    paper_identity=identity,
                    source_url=exact_pdfs[0].url,
                    retrieved_at=args.retrieved_at,
                    timeout_seconds=args.timeout,
                    max_bytes=args.max_bytes,
                )
            packet_path = (
                f"data/papers/{identity.paper_id}/sources/"
                f"{result.packet.source_document_id}/source-packet.json"
            )
            return {
                "paper_id": identity.paper_id,
                "status": "acquired",
                "source_document_id": result.packet.source_document_id,
                "packet_path": packet_path,
                "format": result.packet.format,
                "warnings": list(result.warnings),
                "error": None,
            }
        except Exception as exc:
            return {
                "paper_id": identity.paper_id,
                "status": "failed",
                "source_document_id": None,
                "packet_path": None,
                "format": None,
                "warnings": [],
                "error": f"{type(exc).__name__}: {exc}",
            }

    with ThreadPoolExecutor(max_workers=args.max_concurrent) as executor:
        results = list(executor.map(acquire, identities))
    payload: dict[str, object] = {
        "schema_version": "2.0",
        "workshop_id": args.workshop_id,
        "workshop_manifest_hash": manifest.manifest_hash,
        "retrieved_at": args.retrieved_at,
        "max_concurrent": args.max_concurrent,
        "results": results,
    }
    payload["source_run_hash"] = sha256_json(payload)
    output_path = f"data/workshops/{args.workshop_id}/source-acquisition.json"
    store.write_json(output_path, payload)
    acquired = sum(item["status"] == "acquired" for item in results)
    return {
        "workshop_id": args.workshop_id,
        "source_acquisition_path": output_path,
        "acquired": acquired,
        "failed": len(results) - acquired,
    }


def cmd_reconcile_sources(args: argparse.Namespace) -> dict[str, object]:
    """Validate current frozen sources while preserving acquisition attempts."""

    store = ArtifactStore(args.root)
    manifest = WorkshopCorpusManifest.model_validate_json(args.manifest.read_bytes())
    acquisition = json.loads(args.acquisition.read_text(encoding="utf-8"))
    if acquisition.get("workshop_id") != args.workshop_id:
        raise ValueError("source acquisition belongs to another workshop")
    if acquisition.get("workshop_manifest_hash") != manifest.manifest_hash:
        raise ValueError("source acquisition is not bound to this workshop manifest")

    results: list[dict[str, object]] = []
    for entry in manifest.entries:
        if entry.paper_id is None:
            results.append(
                {
                    "paper_id": None,
                    "entry_id": entry.entry_id,
                    "status": "not_ready",
                    "packet_path": None,
                    "source_document_id": None,
                    "format": None,
                    "error": "workshop entry has no resolved paper identity",
                }
            )
            continue
        packet_paths = sorted(
            (
                args.root / "data" / "papers" / entry.paper_id / "sources"
            ).glob("*/source-packet.json")
        )
        if len(packet_paths) != 1:
            results.append(
                {
                    "paper_id": entry.paper_id,
                    "entry_id": entry.entry_id,
                    "status": "not_ready",
                    "packet_path": None,
                    "source_document_id": None,
                    "format": None,
                    "error": f"expected exactly one source packet; found {len(packet_paths)}",
                }
            )
            continue
        try:
            packet_path = packet_paths[0]
            packet = SourcePacket.model_validate_json(packet_path.read_bytes())
            if packet.paper_id != entry.paper_id:
                raise ValueError("source packet paper_id does not match workshop entry")
            original = store.resolve(packet.original_path).read_bytes()
            if sha256_bytes(original) != packet.original_sha256:
                raise ValueError("original source bytes do not match source packet")
            normalized = store.resolve(packet.normalized_path).read_text(encoding="utf-8")
            packet.validate_normalized_text(normalized)
            results.append(
                {
                    "paper_id": entry.paper_id,
                    "entry_id": entry.entry_id,
                    "status": "ready",
                    "packet_path": packet_path.relative_to(args.root).as_posix(),
                    "source_document_id": packet.source_document_id,
                    "format": packet.format,
                    "error": None,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "paper_id": entry.paper_id,
                    "entry_id": entry.entry_id,
                    "status": "not_ready",
                    "packet_path": packet_paths[0].relative_to(args.root).as_posix(),
                    "source_document_id": None,
                    "format": None,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    ready = sum(item["status"] == "ready" for item in results)
    payload: dict[str, object] = {
        "schema_version": "2.0",
        "workshop_id": args.workshop_id,
        "workshop_manifest_hash": manifest.manifest_hash,
        "reconciled_at": args.reconciled_at,
        "acquisition_attempt": {
            "path": store.relative(args.acquisition),
            "source_run_hash": acquisition["source_run_hash"],
        },
        "expected": manifest.accounting.declared,
        "ready": ready,
        "not_ready": len(results) - ready,
        "results": results,
    }
    payload["source_readiness_hash"] = sha256_json(payload)
    output_path = f"data/workshops/{args.workshop_id}/source-readiness.json"
    store.write_json(output_path, payload)
    return {
        "workshop_id": args.workshop_id,
        "source_readiness_path": output_path,
        "expected": payload["expected"],
        "ready": ready,
        "not_ready": len(results) - ready,
    }


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(description=__doc__)
    top.add_argument("--root", type=Path, default=ROOT)
    sub = top.add_subparsers(dest="command", required=True)
    known = sub.add_parser("extract-known-url")
    known.add_argument("--spec", type=Path, required=True)
    known.add_argument("--declared-count", type=int, required=True)
    known.add_argument("--response", type=Path)
    known.add_argument("--retrieved-at")
    known.add_argument("--timeout", type=int, default=30)
    known.add_argument("--max-bytes", type=int, default=5_000_000)
    known.set_defaults(func=cmd_extract_known_url)
    resolve = sub.add_parser("resolve-cvf")
    resolve.add_argument("--workshop-id", required=True)
    resolve.add_argument("--manifest", type=Path, required=True)
    resolve.add_argument(
        "--page",
        nargs=2,
        action="append",
        metavar=("SOURCE_URL", "FROZEN_HTML"),
        required=True,
    )
    resolve.add_argument("--identity", type=Path, action="append", default=[])
    resolve.set_defaults(func=cmd_resolve_cvf)
    overlays = sub.add_parser("materialize-overlays")
    overlays.add_argument("--workshop-id", required=True)
    overlays.add_argument(
        "--skill-dir",
        type=Path,
        default=ROOT / ".claude/skills/workshop-analysis",
    )
    overlays.set_defaults(func=cmd_materialize_overlays)
    core = sub.add_parser("build-core-inputs")
    core.add_argument("--workshop-id", required=True)
    core.add_argument("--investigation-id", required=True)
    core.add_argument("--manifest", type=Path, required=True)
    core.add_argument("--frozen-at", required=True)
    core.set_defaults(func=cmd_build_core_inputs)
    sources = sub.add_parser("fetch-sources")
    sources.add_argument("--workshop-id", required=True)
    sources.add_argument("--manifest", type=Path, required=True)
    sources.add_argument("--retrieved-at", required=True)
    sources.add_argument("--max-concurrent", type=int, default=4)
    sources.add_argument("--timeout", type=int, default=30)
    sources.add_argument("--max-bytes", type=int, default=75_000_000)
    sources.set_defaults(func=cmd_fetch_sources)
    readiness = sub.add_parser("reconcile-sources")
    readiness.add_argument("--workshop-id", required=True)
    readiness.add_argument("--manifest", type=Path, required=True)
    readiness.add_argument("--acquisition", type=Path, required=True)
    readiness.add_argument("--reconciled-at", required=True)
    readiness.set_defaults(func=cmd_reconcile_sources)
    return top


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result = args.func(args)
    except Exception as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
