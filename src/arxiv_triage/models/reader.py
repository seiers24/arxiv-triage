"""Paper-reader task and result contracts."""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import Field, model_validator

from .base import ContractModel, NonNegativeInt, Sha256, Text
from .paper import PaperIdentity
from .source import SourcePacket


class ReaderFocus(ContractModel):
    component: Text
    skill_hash: Sha256 | None
    questions: list[Text]


class ReaderTask(ContractModel):
    schema_version: Literal["2.0"]
    job_type: Literal["paper_read"]
    agent_run_id: Text
    investigation_id: Text
    paper_identity: PaperIdentity
    source_packet: SourcePacket
    focus: ReaderFocus
    output_schema_version: Literal["2.0"]
    input_hash: Sha256

    @model_validator(mode="after")
    def paper_and_source_are_compatible(self) -> Self:
        if self.paper_identity.paper_id != self.source_packet.paper_id:
            raise ValueError("source packet paper_id does not match paper identity")
        return self

    def validate_record(
        self, value: "ReaderRecordDraft", *, normalized_text: str
    ) -> "ReaderRecordDraft":
        if value.agent_run_id != self.agent_run_id:
            raise ValueError("reader record agent_run_id does not match task")
        if value.investigation_id != self.investigation_id:
            raise ValueError("reader record investigation_id does not match task")
        if value.paper_id != self.paper_identity.paper_id:
            raise ValueError("reader record paper_id does not match task")
        if value.source_document_id != self.source_packet.source_document_id:
            raise ValueError("reader record source_document_id does not match task")
        if value.input_hash != self.input_hash:
            raise ValueError("reader record input_hash does not match task")
        self.source_packet.validate_normalized_text(normalized_text)
        for claim in value.claims:
            if claim.source_locator is not None:
                self.source_packet.validate_locator(
                    **claim.source_locator.model_dump(),
                    normalized_text=normalized_text,
                )
        return value


class SourceLocator(ContractModel):
    document_sha256: Sha256
    section_id: Text
    start_char: NonNegativeInt
    end_char: NonNegativeInt
    quote: Text

    @model_validator(mode="after")
    def nonempty_range(self) -> Self:
        if self.end_char <= self.start_char:
            raise ValueError("source locator end_char must be greater than start_char")
        return self


class Claim(ContractModel):
    claim_id: Text
    claim_kind: Literal["problem", "method", "result", "limitation", "novelty_claim"]
    text: Text
    source_locator: SourceLocator | None
    evidence_modality: Literal[
        "experiment",
        "simulation",
        "theory",
        "observational",
        "qualitative",
        "none_stated",
    ]
    execution_environment: Literal[
        "real_hardware",
        "simulated_hardware",
        "software_runtime",
        "dataset_only",
        "not_applicable",
        "none_stated",
    ]
    provenance: Literal["paper_stated", "analyst_inferred"]
    status: Literal["unverified"]

    @model_validator(mode="after")
    def provenance_matches_evidence(self) -> Self:
        if self.provenance == "analyst_inferred":
            if self.source_locator is not None:
                raise ValueError("an analyst_inferred claim cannot have a source locator")
            if self.evidence_modality != "none_stated":
                raise ValueError("an analyst_inferred claim must use none_stated evidence")
        elif self.source_locator is None:
            raise ValueError("a paper_stated claim requires a source locator")
        return self


class ReaderRecordDraft(ContractModel):
    """Non-canonical shape pending definitions for five nested collections.

    Section 8.2 names these collections but does not specify their element
    schemas. ``Any`` is intentional here: this draft supports development of
    the expressly defined claim and identity invariants, but must not be used
    for canonical promotion.
    """

    schema_version: Literal["2.0"]
    role: Literal["paper_reader"]
    job_type: Literal["paper_read"]
    agent_run_id: Text
    investigation_id: Text
    paper_id: Text
    source_document_id: Text
    input_hash: Sha256
    problem: Text
    method: Text
    contributions: list[Any]
    claims: list[Claim] = Field(min_length=1)
    experimental_evidence: list[Any]
    limitations: list[Any]
    assumptions: list[Any]
    focused_observations: list[Any]

    @model_validator(mode="after")
    def claim_ids_are_unique(self) -> Self:
        ids = [claim.claim_id for claim in self.claims]
        if len(ids) != len(set(ids)):
            raise ValueError("reader claim_id values must be unique")
        return self
