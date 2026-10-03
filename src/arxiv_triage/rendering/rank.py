"""Deterministic objective-profile ranking."""

from __future__ import annotations

from typing import Any, Iterable

from arxiv_triage.models import CriticRecord, ObjectiveProfile, sha256_json


def build_ranking_artifact(
    objective_profile: ObjectiveProfile,
    records: Iterable[CriticRecord],
) -> dict[str, Any]:
    """Rank canonical critic assessments without making new judgments.

    A gate criterion passes when its supplied 0..5 assessment is nonzero. The
    numeric total is the weighted mean of declared criteria, or zero when all
    weights are zero. Uncertain assessments remain visible and do not silently
    alter the arithmetic.
    """

    criteria = {item.criterion_id: item for item in objective_profile.criteria}
    rows: list[dict[str, Any]] = []
    for record in records:
        assessments = {item.criterion_id: item for item in record.objective_assessments}
        if assessments.keys() != criteria.keys():
            raise ValueError("critic record does not cover the ranking objective")
        weighted_sum = sum(
            float(criteria[key].weight) * assessments[key].score for key in criteria
        )
        total_weight = sum(float(item.weight) for item in criteria.values())
        total_score = weighted_sum / total_weight if total_weight else 0.0
        gate_passed = all(
            not criterion.gate or assessments[key].score > 0
            for key, criterion in criteria.items()
        )
        rows.append(
            {
                "paper_id": record.paper_id,
                "gate_passed": gate_passed,
                "total_score": round(total_score, 6),
                "uncertain": any(item.uncertain for item in assessments.values())
                or record.human_review_required,
                "criterion_scores": {
                    key: assessments[key].score for key in criteria
                },
            }
        )
    rows.sort(
        key=lambda row: (
            not row["gate_passed"],
            -row["total_score"],
            row["paper_id"],
        )
    )
    for ordinal, row in enumerate(rows, start=1):
        row["rank"] = ordinal
    artifact: dict[str, Any] = {
        "schema_version": "2.0",
        "objective_profile_hash": objective_profile.profile_hash,
        "rows": rows,
    }
    artifact["ranking_hash"] = sha256_json(artifact)
    return artifact


__all__ = ["build_ranking_artifact"]
