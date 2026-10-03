"""Closed candidate-set and abstract-screening contracts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, Self

from pydantic import Field, model_validator

from .base import (
    ContractModel,
    Identifier,
    NonNegativeInt,
    PositiveInt,
    Sha256,
    Text,
    UtcTimestamp,
    require_self_hash,
)
from .investigation import ObjectiveProfile
from .paper import PaperIdentity


def _require_unique(values: list[str], name: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{name} values must be unique")


class ScreeningScope(ContractModel):
    """The exact semantic inclusion boundary exposed to the screener."""

    schema_version: Literal["2.0"]
    question: Text
    inclusion_rules: list[Text] = Field(min_length=1)
    exclusion_rules: list[Text]
    scope_hash: Sha256

    @model_validator(mode="after")
    def rules_and_hash_are_valid(self) -> Self:
        _require_unique(self.inclusion_rules, "inclusion_rules")
        _require_unique(self.exclusion_rules, "exclusion_rules")
        require_self_hash(self, "scope_hash")
        return self


class CandidatePaper(ContractModel):
    """One immutable paper candidate as supplied to semantic screening."""

    schema_version: Literal["2.0"]
    paper_identity: PaperIdentity
    abstract: Text | None
    discovery_refs: list[Identifier] = Field(min_length=1)
    candidate_hash: Sha256

    @model_validator(mode="after")
    def references_and_hash_are_valid(self) -> Self:
        _require_unique(self.discovery_refs, "discovery_refs")
        require_self_hash(self, "candidate_hash")
        return self


class CandidateSet(ContractModel):
    """Ordered, immutable result of completed discovery."""

    schema_version: Literal["2.0"]
    investigation_id: Identifier
    search_plan_hash: Sha256
    discovery_ledger_hash: Sha256
    frozen_at: UtcTimestamp
    candidates: list[CandidatePaper]
    candidate_set_hash: Sha256

    @model_validator(mode="after")
    def candidates_and_hash_are_valid(self) -> Self:
        paper_ids = [candidate.paper_identity.paper_id for candidate in self.candidates]
        candidate_hashes = [candidate.candidate_hash for candidate in self.candidates]
        _require_unique(paper_ids, "candidate paper_id")
        _require_unique(candidate_hashes, "candidate_hash")
        require_self_hash(self, "candidate_set_hash")
        return self


class ScreeningEvidenceSpan(ContractModel):
    field: Literal["title", "abstract"]
    start_char: NonNegativeInt
    end_char: NonNegativeInt
    quote: Text

    @model_validator(mode="after")
    def range_is_nonempty(self) -> Self:
        if self.end_char <= self.start_char:
            raise ValueError("screening evidence end_char must be greater than start_char")
        return self

    def validate_against(self, candidate: CandidatePaper) -> None:
        source = (
            candidate.paper_identity.title
            if self.field == "title"
            else candidate.abstract
        )
        if source is None:
            raise ValueError("abstract evidence is invalid when candidate abstract is null")
        if self.end_char > len(source):
            raise ValueError("screening evidence span exceeds its candidate field")
        if source[self.start_char : self.end_char] != self.quote:
            raise ValueError("screening evidence quote does not reconstruct exactly")


class ScreeningTask(ContractModel):
    schema_version: Literal["2.0"]
    job_type: Literal["paper_screen"]
    agent_run_id: Identifier
    investigation_id: Identifier
    screening_batch_id: Identifier
    candidate_set_hash: Sha256
    batch_ordinal: PositiveInt
    objective_profile: ObjectiveProfile
    screening_scope: ScreeningScope
    candidates: list[CandidatePaper] = Field(min_length=1)
    batch_size_limit: PositiveInt
    output_schema_version: Literal["2.0"]
    input_hash: Sha256

    @model_validator(mode="after")
    def batch_and_hash_are_valid(self) -> Self:
        if len(self.candidates) > self.batch_size_limit:
            raise ValueError("candidate batch exceeds batch_size_limit")
        paper_ids = [candidate.paper_identity.paper_id for candidate in self.candidates]
        candidate_hashes = [candidate.candidate_hash for candidate in self.candidates]
        _require_unique(paper_ids, "candidate paper_id")
        _require_unique(candidate_hashes, "candidate_hash")
        require_self_hash(self, "input_hash")
        return self

    def validate_record(self, record: "ScreeningRecord") -> "ScreeningRecord":
        bindings = {
            "agent_run_id": self.agent_run_id,
            "investigation_id": self.investigation_id,
            "screening_batch_id": self.screening_batch_id,
            "candidate_set_hash": self.candidate_set_hash,
            "objective_profile_hash": self.objective_profile.profile_hash,
            "screening_scope_hash": self.screening_scope.scope_hash,
            "input_hash": self.input_hash,
        }
        for field_name, expected in bindings.items():
            if getattr(record, field_name) != expected:
                raise ValueError(f"screening record {field_name} does not match task")

        expected_candidates = [
            (candidate.paper_identity.paper_id, candidate.candidate_hash)
            for candidate in self.candidates
        ]
        actual_candidates = [
            (decision.paper_id, decision.candidate_hash)
            for decision in record.decisions
        ]
        if actual_candidates != expected_candidates:
            raise ValueError(
                "screening decisions must cover task candidates exactly and in order"
            )

        candidate_by_id = {
            candidate.paper_identity.paper_id: candidate for candidate in self.candidates
        }
        for decision in record.decisions:
            candidate = candidate_by_id[decision.paper_id]
            for span in decision.evidence_spans:
                span.validate_against(candidate)
        return record


class ScreeningDecision(ContractModel):
    paper_id: Identifier
    candidate_hash: Sha256
    state: Literal["selected", "screened_out", "needs_review"]
    reason: Text
    evidence_spans: list[ScreeningEvidenceSpan]

    @model_validator(mode="after")
    def spans_are_unique(self) -> Self:
        keys = [
            (span.field, span.start_char, span.end_char, span.quote)
            for span in self.evidence_spans
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("screening evidence spans must be unique")
        return self


class ScreeningRecord(ContractModel):
    schema_version: Literal["2.0"]
    role: Literal["paper_screener"]
    job_type: Literal["paper_screen"]
    agent_run_id: Identifier
    investigation_id: Identifier
    screening_batch_id: Identifier
    candidate_set_hash: Sha256
    objective_profile_hash: Sha256
    screening_scope_hash: Sha256
    input_hash: Sha256
    decisions: list[ScreeningDecision]

    @model_validator(mode="after")
    def decision_identities_are_unique(self) -> Self:
        paper_ids = [decision.paper_id for decision in self.decisions]
        candidate_hashes = [decision.candidate_hash for decision in self.decisions]
        _require_unique(paper_ids, "screening decision paper_id")
        _require_unique(candidate_hashes, "screening decision candidate_hash")
        return self


def validate_screening_output(
    task: ScreeningTask,
    value: ScreeningRecord | Mapping[str, object] | str | bytes | bytearray,
) -> ScreeningRecord:
    """Parse and atomically bind one screening result to its exact task."""

    record = (
        ScreeningRecord.model_validate_json(value)
        if isinstance(value, (str, bytes, bytearray))
        else ScreeningRecord.model_validate(value)
    )
    return task.validate_record(record)


__all__ = [
    "CandidatePaper",
    "CandidateSet",
    "ScreeningDecision",
    "ScreeningEvidenceSpan",
    "ScreeningRecord",
    "ScreeningScope",
    "ScreeningTask",
    "validate_screening_output",
]
