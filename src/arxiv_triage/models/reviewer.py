"""Corpus-review task and result contracts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, model_validator

from .base import (
    ContractModel,
    Identifier,
    JsonObject,
    NonNegativeInt,
    Sha256,
    Text,
    require_self_hash,
)
from .corpus import CorpusManifest
from .critic import CriticRecord
from .investigation import InvestigationSpec, ObjectiveProfile, SearchPlan
from .reader import ReaderRecord


class CorpusAccounting(ContractModel):
    """Exact whole-corpus counts; invalid equations are rejected outright."""

    expected: NonNegativeInt
    included: NonNegativeInt
    excluded: NonNegativeInt
    membership_unresolved: NonNegativeInt
    complete: NonNegativeInt
    analysis_unresolved: NonNegativeInt
    failed: NonNegativeInt

    @model_validator(mode="after")
    def counts_balance(self) -> Self:
        if self.expected != self.included + self.excluded + self.membership_unresolved:
            raise ValueError("expected must equal all corpus membership dispositions")
        if self.included != self.complete + self.analysis_unresolved + self.failed:
            raise ValueError("included must equal all included-paper outcomes")
        return self

    @property
    def accounting_valid(self) -> bool:
        """Every constructed instance is valid; no serialized flag is needed."""

        return True


class ReviewPaper(ContractModel):
    paper_id: Identifier
    analysis_status: Literal["complete", "analysis_unresolved", "failed"]
    reader_record: ReaderRecord | None
    critic_record: CriticRecord | None

    @model_validator(mode="after")
    def records_match_status(self) -> Self:
        if self.reader_record is not None and self.reader_record.paper_id != self.paper_id:
            raise ValueError("review paper reader_record paper_id does not match")
        if self.critic_record is not None and self.critic_record.paper_id != self.paper_id:
            raise ValueError("review paper critic_record paper_id does not match")
        if self.critic_record is not None:
            if self.reader_record is None:
                raise ValueError("a critic record requires its canonical reader record")
            if self.critic_record.reader_run_id != self.reader_record.agent_run_id:
                raise ValueError("review paper critic record does not reference its reader")

        if self.analysis_status == "failed":
            if self.critic_record is not None:
                raise ValueError("a failed paper cannot have a canonical critic record")
            return self
        if self.reader_record is None or self.critic_record is None:
            raise ValueError("a non-failed paper requires canonical reader and critic records")

        claims = {claim.claim_id: claim for claim in self.reader_record.claims}
        verdicts = {
            verdict.claim_id: verdict for verdict in self.critic_record.verdicts
        }
        if verdicts.keys() != claims.keys():
            raise ValueError("review paper critic must cover exactly every reader claim")
        for claim_id, verdict in verdicts.items():
            if claims[claim_id].source_locator is None and verdict.status == "supported":
                raise ValueError("review paper cannot support a claim without a locator")
        supported = {
            claim_id
            for claim_id, verdict in verdicts.items()
            if verdict.status == "supported"
        }
        for assessment in self.critic_record.objective_assessments:
            if not set(assessment.evidence_claim_ids) <= supported:
                raise ValueError("review paper assessments may cite only supported claims")

        unresolved = (
            any(
                verdict.status != "supported"
                or not verdict.evidence_classification_correct
                for verdict in self.critic_record.verdicts
            )
            or any(
                assessment.uncertain
                for assessment in self.critic_record.objective_assessments
            )
            or self.critic_record.human_review_required
        )
        expected_status = "analysis_unresolved" if unresolved else "complete"
        if self.analysis_status != expected_status:
            raise ValueError("analysis_status does not match the critic record")
        return self


class ReviewerRubric(ContractModel):
    component: Text
    skill_hash: Sha256 | None


class ClaimReviewRef(ContractModel):
    kind: Literal["claim"]
    paper_id: Identifier
    claim_id: Identifier


class VerdictReviewRef(ContractModel):
    kind: Literal["verdict"]
    paper_id: Identifier
    claim_id: Identifier


class AssessmentReviewRef(ContractModel):
    kind: Literal["assessment"]
    paper_id: Identifier
    criterion_id: Identifier


class CorpusEntryReviewRef(ContractModel):
    kind: Literal["corpus_entry"]
    paper_id: Identifier


ReviewEvidenceRef = Annotated[
    ClaimReviewRef | VerdictReviewRef | AssessmentReviewRef | CorpusEntryReviewRef,
    Field(discriminator="kind"),
]


class ReviewFinding(ContractModel):
    finding_id: Identifier
    text: Text
    evidence_refs: list[ReviewEvidenceRef] = Field(min_length=1)
    provenance: Literal["reviewer_inferred"]
    uncertain: StrictBool


class ReviewChallenge(ContractModel):
    challenge_id: Identifier
    target: ReviewEvidenceRef
    text: Text
    evidence_refs: list[ReviewEvidenceRef]
    uncertain: StrictBool


class ReviewerTask(ContractModel):
    schema_version: Literal["2.0"]
    job_type: Literal["corpus_review"]
    agent_run_id: Identifier
    investigation_id: Identifier
    investigation_spec: InvestigationSpec
    objective_profile: ObjectiveProfile
    search_plan: SearchPlan
    corpus_manifest: CorpusManifest
    corpus_accounting: CorpusAccounting
    papers: list[ReviewPaper]
    ranking_artifact: JsonObject | None
    reviewer_rubric: ReviewerRubric
    input_hash: Sha256

    @model_validator(mode="after")
    def task_inputs_are_compatible(self) -> Self:
        if self.investigation_spec.investigation_id != self.investigation_id:
            raise ValueError("investigation spec does not match reviewer task")
        if self.corpus_manifest.investigation_id != self.investigation_id:
            raise ValueError("corpus manifest does not match reviewer task")
        if self.corpus_manifest.search_plan_hash != self.search_plan.search_plan_hash:
            raise ValueError("corpus manifest does not reference the supplied search plan")
        components = {
            self.objective_profile.component,
            self.search_plan.component,
            self.reviewer_rubric.component,
        }
        if len(components) != 1:
            raise ValueError("reviewer inputs must use one component")

        included_ids = {
            entry.paper_id
            for entry in self.corpus_manifest.entries
            if entry.membership_status == "included"
        }
        paper_ids = [paper.paper_id for paper in self.papers]
        if len(paper_ids) != len(set(paper_ids)):
            raise ValueError("review paper_id values must be unique")
        if set(paper_ids) != included_ids:
            raise ValueError("review task must contain exactly every included paper")
        for paper in self.papers:
            for record in (paper.reader_record, paper.critic_record):
                if record is not None and record.investigation_id != self.investigation_id:
                    raise ValueError("review paper record investigation_id does not match")
            if paper.critic_record is not None:
                criterion_ids = {
                    item.criterion_id
                    for item in paper.critic_record.objective_assessments
                }
                expected_ids = {
                    criterion.criterion_id
                    for criterion in self.objective_profile.criteria
                }
                if criterion_ids != expected_ids:
                    raise ValueError("review critic record does not cover objective criteria")

        counts = self.corpus_manifest.counts
        statuses = [paper.analysis_status for paper in self.papers]
        expected_accounting = CorpusAccounting(
            expected=counts.discovered,
            included=counts.included,
            excluded=counts.excluded,
            membership_unresolved=counts.membership_unresolved,
            complete=statuses.count("complete"),
            analysis_unresolved=statuses.count("analysis_unresolved"),
            failed=statuses.count("failed"),
        )
        if self.corpus_accounting != expected_accounting:
            raise ValueError("corpus_accounting does not match manifest and paper outcomes")
        require_self_hash(self, "input_hash")
        return self

    def validate_record(self, value: "ReviewRecord") -> "ReviewRecord":
        if value.agent_run_id != self.agent_run_id:
            raise ValueError("review record agent_run_id does not match task")
        if value.investigation_id != self.investigation_id:
            raise ValueError("review record investigation_id does not match task")
        if value.input_hash != self.input_hash:
            raise ValueError("review record input_hash does not match task")
        if value.corpus_accounting != self.corpus_accounting:
            raise ValueError("review record corpus_accounting does not match task")

        evidence_index: set[tuple[str, str, str | None]] = set()
        for entry in self.corpus_manifest.entries:
            evidence_index.add(("corpus_entry", entry.paper_id, None))
        for paper in self.papers:
            if paper.reader_record is not None:
                for claim in paper.reader_record.claims:
                    evidence_index.add(("claim", paper.paper_id, claim.claim_id))
            if paper.critic_record is not None:
                for verdict in paper.critic_record.verdicts:
                    evidence_index.add(("verdict", paper.paper_id, verdict.claim_id))
                for assessment in paper.critic_record.objective_assessments:
                    evidence_index.add(
                        ("assessment", paper.paper_id, assessment.criterion_id)
                    )

        refs = [ref for finding in value.findings for ref in finding.evidence_refs]
        refs.extend(challenge.target for challenge in value.challenges)
        refs.extend(
            ref for challenge in value.challenges for ref in challenge.evidence_refs
        )
        for ref in refs:
            if isinstance(ref, (ClaimReviewRef, VerdictReviewRef)):
                key = (ref.kind, ref.paper_id, ref.claim_id)
            elif isinstance(ref, AssessmentReviewRef):
                key = (ref.kind, ref.paper_id, ref.criterion_id)
            else:
                key = (ref.kind, ref.paper_id, None)
            if key not in evidence_index:
                raise ValueError(f"review evidence reference does not resolve: {key}")
        return value


class ReviewRecord(ContractModel):
    schema_version: Literal["2.0"]
    role: Literal["reviewer"]
    job_type: Literal["corpus_review"]
    agent_run_id: Identifier
    investigation_id: Identifier
    input_hash: Sha256
    corpus_accounting: CorpusAccounting
    findings: list[ReviewFinding]
    challenges: list[ReviewChallenge]
    human_review_items: list[Identifier]
    report_status: Literal["ready", "ready_with_warnings", "blocked"]

    @model_validator(mode="after")
    def ids_and_report_status_are_consistent(self) -> Self:
        finding_ids = [finding.finding_id for finding in self.findings]
        challenge_ids = [challenge.challenge_id for challenge in self.challenges]
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("review finding_id values must be unique")
        if len(challenge_ids) != len(set(challenge_ids)):
            raise ValueError("review challenge_id values must be unique")
        if len(self.human_review_items) != len(set(self.human_review_items)):
            raise ValueError("human_review_items must be unique")
        if not set(self.human_review_items) <= set(challenge_ids):
            raise ValueError("human_review_items must reference challenge_id values")

        has_visible_warning = bool(self.challenges) or any(
            (
                self.corpus_accounting.membership_unresolved,
                self.corpus_accounting.analysis_unresolved,
                self.corpus_accounting.failed,
            )
        )
        expected_status = (
            "blocked"
            if self.human_review_items
            else "ready_with_warnings"
            if has_visible_warning
            else "ready"
        )
        if self.report_status != expected_status:
            raise ValueError("report_status does not match review challenges and accounting")
        return self


def validate_reviewer_output(
    task: ReviewerTask,
    value: ReviewRecord | Mapping[str, object] | str | bytes | bytearray,
) -> ReviewRecord:
    """Parse, validate, and bind reviewer output through one public gateway."""

    record = (
        ReviewRecord.model_validate_json(value)
        if isinstance(value, (str, bytes, bytearray))
        else ReviewRecord.model_validate(value)
    )
    return task.validate_record(record)


__all__ = [
    "AssessmentReviewRef",
    "ClaimReviewRef",
    "CorpusAccounting",
    "CorpusEntryReviewRef",
    "ReviewChallenge",
    "ReviewEvidenceRef",
    "ReviewFinding",
    "ReviewPaper",
    "ReviewRecord",
    "ReviewerRubric",
    "ReviewerTask",
    "VerdictReviewRef",
    "validate_reviewer_output",
]
