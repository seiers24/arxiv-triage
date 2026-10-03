from __future__ import annotations

from pathlib import Path

from arxiv_triage.models import CriticRecord, ObjectiveProfile
from arxiv_triage.workshop import WorkshopRankingPolicy, build_workshop_ranking


ROOT = Path(__file__).resolve().parents[2]


def load_profile() -> ObjectiveProfile:
    return ObjectiveProfile.model_validate_json(
        (ROOT / "objectives/edge-cvpr-2026.json").read_bytes()
    )


def load_policy() -> WorkshopRankingPolicy:
    return WorkshopRankingPolicy.model_validate_json(
        (ROOT / "objectives/edge-cvpr-2026-ranking-policy.json").read_bytes()
    )


def record(paper_id: str, scores: list[int], *, uncertain: bool = False) -> CriticRecord:
    profile = load_profile()
    return CriticRecord.model_validate(
        {
            "schema_version": "2.0",
            "role": "critic",
            "job_type": "paper_critique",
            "agent_run_id": f"run-{paper_id}",
            "investigation_id": "inv-edge-2026",
            "paper_id": paper_id,
            "reader_run_id": f"reader-{paper_id}",
            "input_hash": "a" * 64,
            "verdicts": [],
            "objective_assessments": [
                {
                    "criterion_id": criterion.criterion_id,
                    "score": score,
                    "reason": "Fixture assessment",
                    "evidence_claim_ids": [],
                    "assumptions": [],
                    "uncertain": uncertain,
                }
                for criterion, score in zip(profile.criteria, scores, strict=True)
            ],
            "human_review_reasons": [],
        }
    )


def test_edge_objective_and_policy_are_hash_valid() -> None:
    profile = load_profile()
    policy = load_policy()
    assert policy.objective_profile_hash == profile.profile_hash
    assert [item.criterion_id for item in profile.criteria] == [
        "workshop_fit",
        "evidence_strength",
        "efficiency_result",
        "deployment_realism",
        "extension_leverage",
    ]


def test_workshop_top_tier_is_threshold_based_and_never_fixed_k() -> None:
    ranking = build_workshop_ranking(
        load_profile(),
        load_policy(),
        [
            record("paper-qualifies", [5, 4, 4, 4, 4]),
            record("paper-low-evidence", [5, 2, 5, 5, 5]),
            record("paper-uncertain", [5, 5, 5, 5, 5], uncertain=True),
            record("paper-low-total", [4, 3, 3, 2, 2]),
        ],
    )
    rows = {row["paper_id"]: row for row in ranking["rows"]}
    assert ranking["workshop_policy"] == load_policy().model_dump(mode="json")
    assert ranking["workshop_policy_hash"] == load_policy().policy_hash
    assert rows["paper-qualifies"]["top_tier"] is True
    assert rows["paper-low-evidence"]["top_tier_failures"] == [
        "criterion:evidence_strength"
    ]
    assert rows["paper-uncertain"]["top_tier_failures"] == ["uncertainty"]
    assert "total_score" in rows["paper-low-total"]["top_tier_failures"]
    assert sum(row["top_tier"] for row in rows.values()) == 1
