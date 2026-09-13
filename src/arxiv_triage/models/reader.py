"""Paper-reader task and result contracts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, Self

from pydantic import model_validator

from .base import (
    ContractModel,
    Identifier,
    NonNegativeInt,
    Sha256,
    Text,
    require_self_hash,
    sha256_bytes,
)
from .paper import PaperIdentity
from .source import SourcePacket


class ReaderFocus(ContractModel):
    component: Text
    skill_hash: Sha256 | None
    questions: list[Text]


class ReaderTask(ContractModel):
    schema_version: Literal["2.0"]
    job_type: Literal["paper_read"]
    agent_run_id: Identifier
    investigation_id: Identifier
    paper_identity: PaperIdentity
    source_packet: SourcePacket
    source_text: Text
    focus: ReaderFocus
    output_schema_version: Literal["2.0"]
    input_hash: Sha256

    @model_validator(mode="after")
    def paper_and_source_are_compatible(self) -> Self:
        if self.paper_identity.paper_id != self.source_packet.paper_id:
            raise ValueError("source packet paper_id does not match paper identity")
        if sha256_bytes(self.source_text.encode("utf-8")) != self.source_packet.normalized_sha256:
            raise ValueError("source_text hash does not match source packet")
        self.source_packet.validate_normalized_text(self.source_text)
        require_self_hash(self, "input_hash")
        return self

    def validate_record(self, value: "ReaderRecord") -> "ReaderRecord":
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
        self.source_packet.validate_normalized_text(self.source_text)
        for claim in value.claims:
            if claim.source_locator is not None:
                self.source_packet.validate_locator(
                    **claim.source_locator.model_dump(),
                    normalized_text=self.source_text,
                )
        return value


class SourceLocator(ContractModel):
    document_sha256: Sha256
    section_id: Identifier
    start_char: NonNegativeInt
    end_char: NonNegativeInt
    quote: Text

    @model_validator(mode="after")
    def nonempty_range(self) -> Self:
        if self.end_char <= self.start_char:
            raise ValueError("source locator end_char must be greater than start_char")
        return self


class Claim(ContractModel):
    claim_id: Identifier
    claim_kind: Literal[
        "problem",
        "method",
        "result",
        "contribution",
        "limitation",
        "assumption",
        "novelty_claim",
    ]
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


class ReaderRecord(ContractModel):
    """Canonical paper-reader result with claims as its evidence collection."""

    schema_version: Literal["2.0"]
    role: Literal["paper_reader"]
    job_type: Literal["paper_read"]
    agent_run_id: Identifier
    investigation_id: Identifier
    paper_id: Identifier
    source_document_id: Identifier
    input_hash: Sha256
    problem: Text
    method: Text
    claims: list[Claim]
    warnings: list[Text]

    @model_validator(mode="after")
    def claims_are_consistent(self) -> Self:
        ids = [claim.claim_id for claim in self.claims]
        if len(ids) != len(set(ids)):
            raise ValueError("reader claim_id values must be unique")
        if not self.claims and not self.warnings:
            raise ValueError("a reader record without claims must include a warning")
        return self


def validate_reader_output(
    task: ReaderTask,
    value: ReaderRecord | Mapping[str, object] | str | bytes | bytearray,
) -> ReaderRecord:
    """Validate and bind reader output to its task and frozen source."""

    record = (
        ReaderRecord.model_validate_json(value)
        if isinstance(value, (str, bytes, bytearray))
        else ReaderRecord.model_validate(value)
    )
    return task.validate_record(record)
