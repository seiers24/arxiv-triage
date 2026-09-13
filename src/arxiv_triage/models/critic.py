"""Per-paper critic task and result contracts."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import StrictBool, model_validator

from .base import ContractModel, Score, Sha256, Text
from .investigation import ObjectiveProfile
from .paper import PaperIdentity
from .reader import ReaderRecordDraft
from .source import SourcePacket


class CriticRubric(ContractModel):
    component: Text
    skill_hash: Sha256 | None


class ClaimVerdict(ContractModel):
    claim_id: Text
    status: Literal["supported", "unsupported", "overclaimed"]
    evidence_classification_correct: StrictBool
    reason: Text


class ObjectiveAssessment(ContractModel):
    criterion_id: Text
    score: Score
    label: None
    reason: Text
    evidence_claim_ids: list[Text]
    assumptions: list[Text]
    uncertain: StrictBool


class CriticRecordDraft(ContractModel):
    """Non-canonical result pending assessment-label contract completion."""

    schema_version: Literal["2.0"]
    role: Literal["critic"]
    job_type: Literal["paper_critique"]
    agent_run_id: Text
    investigation_id: Text
    paper_id: Text
    reader_run_id: Text
    input_hash: Sha256
    verdicts: list[ClaimVerdict]
    objective_assessments: list[ObjectiveAssessment]
    human_review_required: StrictBool
    human_review_reasons: list[Text]

    @model_validator(mode="after")
    def referenced_ids_are_unique(self) -> Self:
        verdict_ids = [verdict.claim_id for verdict in self.verdicts]
        if len(verdict_ids) != len(set(verdict_ids)):
            raise ValueError("critic verdict claim_id values must be unique")
        criterion_ids = [item.criterion_id for item in self.objective_assessments]
        if len(criterion_ids) != len(set(criterion_ids)):
            raise ValueError("objective assessment criterion_id values must be unique")
        return self


class CriticTaskDraft(ContractModel):
    """Non-canonical task because its embedded reader record is incomplete."""

    schema_version: Literal["2.0"]
    job_type: Literal["paper_critique"]
    agent_run_id: Text
    investigation_id: Text
    paper_identity: PaperIdentity
    source_packet: SourcePacket
    reader_record: ReaderRecordDraft
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
        if self.reader_record.source_document_id != self.source_packet.source_document_id:
            raise ValueError("reader record does not reference the supplied source packet")
        return self

    def validate_record(self, value: CriticRecordDraft) -> CriticRecordDraft:
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
        if not assessments.keys() <= criteria.keys():
            raise ValueError("objective assessment references an undeclared criterion")

        supported = {
            claim_id for claim_id, verdict in verdicts.items() if verdict.status == "supported"
        }
        for assessment in assessments.values():
            if not set(assessment.evidence_claim_ids) <= supported:
                raise ValueError("objective assessments may cite only supported claims")
        return value
