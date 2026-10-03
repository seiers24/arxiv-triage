#!/usr/bin/env python3
"""Build the deterministic schema-2.0 ranking for one investigation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arxiv_triage.models import CriticRecord, ObjectiveProfile  # noqa: E402
from arxiv_triage.rendering import build_ranking_artifact  # noqa: E402
from arxiv_triage.storage import ArtifactStore  # noqa: E402
from arxiv_triage.workshop import (  # noqa: E402
    WorkshopRankingPolicy,
    build_workshop_ranking,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("investigation_id")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--workshop-policy",
        type=Path,
        help="optional WorkshopRankingPolicy JSON for deterministic top-tier flags",
    )
    args = parser.parse_args(argv)
    try:
        base = args.root / "data/investigations" / args.investigation_id
        profile = ObjectiveProfile.model_validate_json(
            (base / "objective-profile.json").read_bytes()
        )
        records = [
            CriticRecord.model_validate_json(path.read_bytes())
            for path in sorted((base / "papers").glob("*/critic/canonical.json"))
        ]
        if args.workshop_policy is None:
            artifact = build_ranking_artifact(profile, records)
        else:
            policy = WorkshopRankingPolicy.model_validate_json(
                args.workshop_policy.read_bytes()
            )
            artifact = build_workshop_ranking(profile, policy, records)
        ref = ArtifactStore(args.root).write_json(
            f"data/investigations/{args.investigation_id}/ranking.json", artifact
        )
    except Exception as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"ranking_path": ref.path, "papers": len(records)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
