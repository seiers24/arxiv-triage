"""Deterministic preparation of reader, critic, and reviewer tasks."""

from __future__ import annotations

from typing import Any, Iterable

from arxiv_triage.models import (
    CorpusAccounting,
    CorpusManifest,
    CriticRecord,
    CriticRubric,
    CriticTask,
    InvestigationSpec,
    ObjectiveProfile,
    PaperIdentity,
    ReaderFocus,
    ReaderRecord,
    ReaderTask,
    ReviewPaper,
    ReviewerRubric,
    ReviewerTask,
    SearchPlan,
    SourcePacket,
    sha256_json,
)


def prepare_reader_task(
    *,
    agent_run_id: str,
    investigation_id: str,
    paper_identity: PaperIdentity,
    source_packet: SourcePacket,
    source_text: str,
    focus: ReaderFocus,
) -> ReaderTask:
    payload: dict[str, Any] = {
        "schema_version": "2.0",
        "job_type": "paper_read",
        "agent_run_id": agent_run_id,
        "investigation_id": investigation_id,
        "paper_identity": paper_identity.model_dump(mode="json"),
        "source_packet": source_packet.model_dump(mode="json"),
        "source_text": source_text,
        "focus": focus.model_dump(mode="json"),
        "output_schema_version": "2.0",
    }
    payload["input_hash"] = sha256_json(payload)
    return ReaderTask.model_validate(payload)


def prepare_critic_task(
    *,
    agent_run_id: str,
    investigation_id: str,
    paper_identity: PaperIdentity,
    source_packet: SourcePacket,
    source_text: str,
    reader_record: ReaderRecord,
    objective_profile: ObjectiveProfile,
    critic_rubric: CriticRubric,
) -> CriticTask:
    payload: dict[str, Any] = {
        "schema_version": "2.0",
        "job_type": "paper_critique",
        "agent_run_id": agent_run_id,
        "investigation_id": investigation_id,
        "paper_identity": paper_identity.model_dump(mode="json"),
        "source_packet": source_packet.model_dump(mode="json"),
        "source_text": source_text,
        "reader_record": reader_record.model_dump(mode="json"),
        "objective_profile": objective_profile.model_dump(mode="json"),
        "critic_rubric": critic_rubric.model_dump(mode="json"),
    }
    payload["input_hash"] = sha256_json(payload)
    return CriticTask.model_validate(payload)


def analysis_status(record: CriticRecord) -> str:
    unresolved = (
        any(
            verdict.status != "supported"
            or not verdict.evidence_classification_correct
            for verdict in record.verdicts
        )
        or any(item.uncertain for item in record.objective_assessments)
        or record.human_review_required
    )
    return "analysis_unresolved" if unresolved else "complete"


def prepare_reviewer_task(
    *,
    agent_run_id: str,
    investigation_spec: InvestigationSpec,
    objective_profile: ObjectiveProfile,
    search_plan: SearchPlan,
    corpus_manifest: CorpusManifest,
    papers: Iterable[ReviewPaper],
    ranking_artifact: dict[str, Any] | None,
    reviewer_rubric: ReviewerRubric,
) -> ReviewerTask:
    paper_list = list(papers)
    statuses = [paper.analysis_status for paper in paper_list]
    counts = corpus_manifest.counts
    accounting = CorpusAccounting(
        expected=counts.discovered,
        included=counts.included,
        excluded=counts.excluded,
        membership_unresolved=counts.membership_unresolved,
        complete=statuses.count("complete"),
        analysis_unresolved=statuses.count("analysis_unresolved"),
        failed=statuses.count("failed"),
    )
    payload: dict[str, Any] = {
        "schema_version": "2.0",
        "job_type": "corpus_review",
        "agent_run_id": agent_run_id,
        "investigation_id": investigation_spec.investigation_id,
        "investigation_spec": investigation_spec.model_dump(mode="json"),
        "objective_profile": objective_profile.model_dump(mode="json"),
        "search_plan": search_plan.model_dump(mode="json"),
        "corpus_manifest": corpus_manifest.model_dump(mode="json"),
        "corpus_accounting": accounting.model_dump(mode="json"),
        "papers": [paper.model_dump(mode="json") for paper in paper_list],
        "ranking_artifact": ranking_artifact,
        "reviewer_rubric": reviewer_rubric.model_dump(mode="json"),
    }
    payload["input_hash"] = sha256_json(payload)
    return ReviewerTask.model_validate(payload)


__all__ = [
    "analysis_status",
    "prepare_critic_task",
    "prepare_reader_task",
    "prepare_reviewer_task",
]
