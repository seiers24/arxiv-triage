"""Deterministic screening partition, task-preparation, and routing helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal, Sequence

from arxiv_triage.models import (
    CandidatePaper,
    CandidateSet,
    ObjectiveProfile,
    ScreeningRecord,
    ScreeningScope,
    ScreeningTask,
    sha256_json,
)

from .guards import GuardViolation


@dataclass(frozen=True, slots=True)
class ScreeningRoute:
    paper_id: str
    membership_status: Literal["included", "excluded", "membership_unresolved"]
    inclusion_reason: str | None
    exclusion_reason: str | None


def partition_candidates(
    candidates: Sequence[CandidatePaper], batch_size_limit: int
) -> tuple[tuple[CandidatePaper, ...], ...]:
    """Partition candidates in their frozen order without omission."""

    if (
        isinstance(batch_size_limit, bool)
        or not isinstance(batch_size_limit, int)
        or batch_size_limit <= 0
    ):
        raise GuardViolation("batch_size_limit must be a positive integer")
    return tuple(
        tuple(candidates[index : index + batch_size_limit])
        for index in range(0, len(candidates), batch_size_limit)
    )


def stable_screening_batch_id(batch_ordinal: int) -> str:
    if isinstance(batch_ordinal, bool) or not isinstance(batch_ordinal, int) or batch_ordinal <= 0:
        raise GuardViolation("batch_ordinal must be a positive integer")
    return f"screening-batch-{batch_ordinal:04d}"


def prepare_screening_task(
    *,
    candidate_set: CandidateSet,
    objective_profile: ObjectiveProfile,
    screening_scope: ScreeningScope,
    batch_ordinal: int,
    batch_size_limit: int,
    agent_run_id: str,
) -> ScreeningTask:
    """Build one self-hashed task from a deterministic candidate partition."""

    screening_batch_id = stable_screening_batch_id(batch_ordinal)
    batches = partition_candidates(candidate_set.candidates, batch_size_limit)
    if batch_ordinal > len(batches):
        raise GuardViolation("batch_ordinal does not identify a non-empty candidate batch")
    payload: dict[str, object] = {
        "schema_version": "2.0",
        "job_type": "paper_screen",
        "agent_run_id": agent_run_id,
        "investigation_id": candidate_set.investigation_id,
        "screening_batch_id": screening_batch_id,
        "candidate_set_hash": candidate_set.candidate_set_hash,
        "batch_ordinal": batch_ordinal,
        "objective_profile": objective_profile.model_dump(mode="json"),
        "screening_scope": screening_scope.model_dump(mode="json"),
        "candidates": [candidate.model_dump(mode="json") for candidate in batches[batch_ordinal - 1]],
        "batch_size_limit": batch_size_limit,
        "output_schema_version": "2.0",
    }
    payload["input_hash"] = sha256_json(payload)
    return ScreeningTask.model_validate(payload)


def route_screening_records(
    *,
    candidate_set: CandidateSet,
    objective_profile: ObjectiveProfile,
    screening_scope: ScreeningScope,
    records: Iterable[ScreeningRecord],
    identity_failure_paper_ids: Iterable[str] = (),
) -> tuple[ScreeningRoute, ...]:
    """Require global semantic-screening coverage and route every candidate."""

    canonical_records = tuple(records)
    batch_ids = [record.screening_batch_id for record in canonical_records]
    if len(batch_ids) != len(set(batch_ids)):
        raise GuardViolation("canonical screening batch IDs must be unique")
    if any(
        record.investigation_id != candidate_set.investigation_id
        or record.candidate_set_hash != candidate_set.candidate_set_hash
        or record.objective_profile_hash != objective_profile.profile_hash
        or record.screening_scope_hash != screening_scope.scope_hash
        for record in canonical_records
    ):
        raise GuardViolation(
            "screening record does not bind the frozen candidates, objective, and scope"
        )

    decisions = [
        decision for record in canonical_records for decision in record.decisions
    ]
    expected = [
        (candidate.paper_identity.paper_id, candidate.candidate_hash)
        for candidate in candidate_set.candidates
    ]
    actual = [(decision.paper_id, decision.candidate_hash) for decision in decisions]
    if len(actual) != len(set(actual)):
        raise GuardViolation("a frozen candidate has more than one screening decision")
    if set(actual) != set(expected):
        raise GuardViolation("screening decisions do not cover every frozen candidate exactly")

    identity_failures = set(identity_failure_paper_ids)
    known_paper_ids = {paper_id for paper_id, _ in expected}
    unknown_failures = identity_failures - known_paper_ids
    if unknown_failures:
        raise GuardViolation("identity failures include a paper outside the candidate set")
    decision_by_paper = {decision.paper_id: decision for decision in decisions}
    routes: list[ScreeningRoute] = []
    for candidate in candidate_set.candidates:
        paper_id = candidate.paper_identity.paper_id
        decision = decision_by_paper[paper_id]
        if paper_id in identity_failures:
            routes.append(ScreeningRoute(paper_id, "membership_unresolved", None, None))
        elif decision.state == "screened_out":
            routes.append(ScreeningRoute(paper_id, "excluded", None, decision.reason))
        else:
            routes.append(ScreeningRoute(paper_id, "included", decision.reason, None))
    return tuple(routes)


def route_authoritative_membership(
    *, candidate_set: CandidateSet, authoritative_membership: bool
) -> tuple[ScreeningRoute, ...]:
    """Include a complete listed population only under an explicit bypass."""

    if not authoritative_membership:
        raise GuardViolation("authoritative membership bypass must be explicit")
    return tuple(
        ScreeningRoute(
            candidate.paper_identity.paper_id,
            "included",
            "Included from authoritative workshop membership",
            None,
        )
        for candidate in candidate_set.candidates
    )


__all__ = [
    "ScreeningRoute",
    "partition_candidates",
    "prepare_screening_task",
    "route_authoritative_membership",
    "route_screening_records",
    "stable_screening_batch_id",
]
