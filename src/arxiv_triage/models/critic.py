"""Per-paper critic task and result contracts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, Self

from pydantic import StrictBool, model_validator

from .base import (
    ContractModel,
    Identifier,
    Score,
    Sha256,
    Text,
    require_self_hash,
    sha256_bytes,
)
from .investigation import ObjectiveProfile
from .paper import PaperIdentity
from .reader import ReaderRecord
from .source import SourcePacket


class CriticRubric(ContractModel):
    component: Text
    skill_hash: Sha256 | None


class ClaimVerdict(ContractModel):
    claim_id: Identifier
    status: Literal["supported", "unsupported", "overclaimed"]
    evidence_classification_correct: StrictBool
    reason: Text


class ObjectiveAssessment(ContractModel):
    """Assessment of one declared integer criterion."""

    criterion_id: Identifier
    score: Score
    reason: Text
    evidence_claim_ids: list[Identifier]
    assumptions: list[Text]
    uncertain: StrictBool

    @model_validator(mode="after")
    def references_are_unique(self) -> Self:
        if len(self.evidence_claim_ids) != len(set(self.evidence_claim_ids)):
            raise ValueError("assessment evidence_claim_ids must be unique")
        if len(self.assumptions) != len(set(self.assumptions)):
            raise ValueError("assessment assumptions must be unique")
        return self


class CriticRecord(ContractModel):
    schema_version: Literal["2.0"]
    role: Literal["critic"]
    job_type: Literal["paper_critique"]
    agent_run_id: Identifier
    investigation_id: Identifier
    paper_id: Identifier
    reader_run_id: Identifier
    input_hash: Sha256
    verdicts: list[ClaimVerdict]
    objective_assessments: list[ObjectiveAssessment]
    human_review_reasons: list[Text]

    @property
    def human_review_required(self) -> bool:
        """Derive review gating instead of trusting a duplicated boolean."""

        return bool(self.human_review_reasons)

    @model_validator(mode="after")
    def referenced_ids_are_unique(self) -> Self:
        verdict_ids = [verdict.claim_id for verdict in self.verdicts]
        if len(verdict_ids) != len(set(verdict_ids)):
            raise ValueError("critic verdict claim_id values must be unique")
        criterion_ids = [item.criterion_id for item in self.objective_assessments]
        if len(criterion_ids) != len(set(criterion_ids)):
            raise ValueError("objective assessment criterion_id values must be unique")
        if len(self.human_review_reasons) != len(set(self.human_review_reasons)):
            raise ValueError("human_review_reasons must be unique")
        return self


class CriticTask(ContractModel):
    schema_version: Literal["2.0"]
    job_type: Literal["paper_critique"]
    agent_run_id: Identifier
    investigation_id: Identifier
    paper_identity: PaperIdentity
    source_packet: SourcePacket
    source_text: Text
    reader_record: ReaderRecord
    objective_profile: ObjectiveProfile
    critic_rubric: CriticRubric
    input_hash: Sha256

    @model_validator(mode="after")
    def task_inputs_are_compatible(self) -> Self:
        paper_id = self.paper_identity.paper_id
        if self.source_packet.paper_id != paper_id:
            raise ValueError("source packet paper_id does not match paper identity")
        if self.reader_record.paper_id != paper_id:
            raise ValueError("reader record paper_id does not match paper identity")
        if self.reader_record.investigation_id != self.investigation_id:
            raise ValueError("reader record investigation_id does not match critic task")
        if self.reader_record.source_document_id != self.source_packet.source_document_id:
            raise ValueError("reader record does not reference the supplied source packet")
        if sha256_bytes(self.source_text.encode("utf-8")) != self.source_packet.normalized_sha256:
            raise ValueError("source_text hash does not match source packet")
        self.source_packet.validate_normalized_text(self.source_text)
        for claim in self.reader_record.claims:
            if claim.source_locator is not None:
                self.source_packet.validate_locator(
                    **claim.source_locator.model_dump(),
                    normalized_text=self.source_text,
                )
        if self.critic_rubric.component != self.objective_profile.component:
            raise ValueError("critic rubric component does not match objective profile")
        require_self_hash(self, "input_hash")
        return self

    def validate_record(self, value: CriticRecord) -> CriticRecord:
        if value.agent_run_id != self.agent_run_id:
            raise ValueError("critic record agent_run_id does not match task")
        if value.investigation_id != self.investigation_id:
            raise ValueError("critic record investigation_id does not match task")
        if value.paper_id != self.paper_identity.paper_id:
            raise ValueError("critic record paper_id does not match task")
        if value.reader_run_id != self.reader_record.agent_run_id:
            raise ValueError("critic record reader_run_id does not match reader record")
        if value.input_hash != self.input_hash:
            raise ValueError("critic record input_hash does not match task")

        claims = {claim.claim_id: claim for claim in self.reader_record.claims}
        verdicts = {verdict.claim_id: verdict for verdict in value.verdicts}
        if verdicts.keys() != claims.keys():
            raise ValueError("critic must return exactly one verdict per reader claim")
        for claim_id, verdict in verdicts.items():
            if claims[claim_id].source_locator is None and verdict.status == "supported":
                raise ValueError("a claim without a source locator cannot be supported")

        criteria = {
            criterion.criterion_id: criterion
            for criterion in self.objective_profile.criteria
        }
        assessments = {
            assessment.criterion_id: assessment
            for assessment in value.objective_assessments
        }
        if assessments.keys() != criteria.keys():
            raise ValueError("critic must assess exactly every declared objective criterion")
        supported = {
            claim_id for claim_id, verdict in verdicts.items() if verdict.status == "supported"
        }
        for assessment in assessments.values():
            if not set(assessment.evidence_claim_ids) <= supported:
                raise ValueError("objective assessments may cite only supported claims")
        return value


def validate_critic_output(
    task: CriticTask,
    value: CriticRecord | Mapping[str, object] | str | bytes | bytearray,
) -> CriticRecord:
    """Parse, validate, and bind critic output through one public gateway."""

    record = (
        CriticRecord.model_validate_json(value)
        if isinstance(value, (str, bytes, bytearray))
        else CriticRecord.model_validate(value)
    )
    return task.validate_record(record)


__all__ = [
    "ClaimVerdict",
    "CriticRecord",
    "CriticRubric",
    "CriticTask",
    "ObjectiveAssessment",
    "validate_critic_output",
]
