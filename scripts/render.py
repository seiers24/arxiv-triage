#!/usr/bin/env python3
"""Render one reviewed schema-2.0 investigation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arxiv_triage.models import (  # noqa: E402
    CorpusManifest,
    ObjectiveProfile,
    PaperIdentity,
    ReviewRecord,
    ReviewerTask,
)
from arxiv_triage.rendering import render_investigation  # noqa: E402
from arxiv_triage.workshop import WorkshopCorpusManifest, WorkshopSpec  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("investigation_id")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--workshop-id")
    args = parser.parse_args(argv)
    try:
        base = args.root / "data/investigations" / args.investigation_id
        corpus = CorpusManifest.model_validate_json((base / "corpus.json").read_bytes())
        profile = ObjectiveProfile.model_validate_json(
            (base / "objective-profile.json").read_bytes()
        )
        review = ReviewRecord.model_validate_json(
            (base / "review/canonical.json").read_bytes()
        )
        task = ReviewerTask.model_validate_json(
            (base / "runs" / review.agent_run_id / "input.json").read_bytes()
        )
        task.validate_record(review)
        if task.ranking_artifact is None:
            raise ValueError("reviewer task has no frozen ranking artifact")
        identities = {
            entry.paper_id: PaperIdentity.model_validate_json(
                (args.root / f"data/papers/{entry.paper_id}/identity.json").read_bytes()
            )
            for entry in corpus.entries
        }
        component_metadata = None
        if task.search_plan.component == "workshop-analysis":
            if not args.workshop_id:
                raise ValueError("workshop rendering requires --workshop-id")
            workshop_base = args.root / "data/workshops" / args.workshop_id
            workshop_spec = WorkshopSpec.model_validate_json(
                (workshop_base / "workshop-spec.json").read_bytes()
            )
            workshop_manifest = WorkshopCorpusManifest.model_validate_json(
                (workshop_base / "resolved-corpus.json").read_bytes()
            )
            if workshop_spec.spec_hash != workshop_manifest.workshop_spec_hash:
                raise ValueError("workshop spec and resolved corpus are not bound")
            workshop_ids = {
                entry.paper_id for entry in workshop_manifest.entries if entry.paper_id
            }
            corpus_ids = {entry.paper_id for entry in corpus.entries}
            if workshop_ids != corpus_ids:
                raise ValueError("workshop and core corpus paper sets do not match")
            component_metadata = {
                "component": "workshop-analysis",
                "workshop_id": workshop_spec.workshop_id,
                "workshop_spec_hash": workshop_spec.spec_hash,
                "workshop_manifest_hash": workshop_manifest.manifest_hash,
                "component_skill_hash": task.reviewer_rubric.skill_hash,
                "workshop_policy_hash": task.ranking_artifact.get(
                    "workshop_policy_hash"
                ),
                "declared": workshop_manifest.accounting.declared,
                "extracted": workshop_manifest.accounting.extracted,
                "identity_resolved": workshop_manifest.accounting.resolved,
                "entries": {
                    entry.paper_id: {
                        "track_id": entry.track_id,
                        "poster_number": entry.poster_number,
                        "resolution_status": entry.resolution_status,
                    }
                    for entry in workshop_manifest.entries
                    if entry.paper_id
                },
            }
        outputs = render_investigation(
            output_directory=args.root / "out" / args.investigation_id,
            corpus_manifest=corpus,
            objective_profile=profile,
            identities=identities,
            papers=task.papers,
            review_record=review,
            ranking_artifact=task.ranking_artifact,
            component_metadata=component_metadata,
        )
    except Exception as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "report": str(outputs.report),
                "papers_csv": str(outputs.papers_csv),
                "human_review": str(outputs.human_review),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
