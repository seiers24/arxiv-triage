"""Deterministic workshop top-tier classification."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from arxiv_triage.models import CriticRecord, ObjectiveProfile, sha256_json
from arxiv_triage.rendering import build_ranking_artifact

from .models import WorkshopRankingPolicy


def build_workshop_ranking(
    objective_profile: ObjectiveProfile,
    policy: WorkshopRankingPolicy,
    records: Iterable[CriticRecord],
) -> dict[str, Any]:
    """Rank paper-local assessments and apply the frozen no-fixed-k policy."""

    if policy.objective_profile_hash != objective_profile.profile_hash:
        raise ValueError("workshop ranking policy targets another objective profile")
    criterion_ids = {criterion.criterion_id for criterion in objective_profile.criteria}
    unknown = set(policy.criterion_minimums).difference(criterion_ids)
    if unknown:
        raise ValueError(f"workshop ranking policy has unknown criteria: {sorted(unknown)}")

    artifact = build_ranking_artifact(objective_profile, records)
    for row in artifact["rows"]:
        failures: list[str] = []
        if not row["gate_passed"]:
            failures.append("objective_gate")
        if row["total_score"] < policy.top_tier_min_total:
            failures.append("total_score")
        for criterion_id, minimum in policy.criterion_minimums.items():
            if row["criterion_scores"][criterion_id] < minimum:
                failures.append(f"criterion:{criterion_id}")
        if policy.exclude_uncertain and row["uncertain"]:
            failures.append("uncertainty")
        row["top_tier"] = not failures
        row["top_tier_failures"] = failures
    artifact["workshop_policy"] = policy.model_dump(mode="json")
    artifact["workshop_policy_hash"] = policy.policy_hash
    artifact["ranking_hash"] = sha256_json(
        {key: value for key, value in artifact.items() if key != "ranking_hash"}
    )
    return artifact


__all__ = ["build_workshop_ranking"]
