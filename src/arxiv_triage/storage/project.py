"""Validate canonical artifacts and project them into SQLite rows."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from arxiv_triage.models import (
    AgentRun,
    CandidateSet,
    CorpusManifest,
    CriticRecord,
    InvestigationSpec,
    ObjectiveProfile,
    OutcomeRecord,
    PaperIdentity,
    PaperStateRecord,
    ReaderRecord,
    ReviewRecord,
    ScreeningRecord,
    SearchPlan,
    SourcePacket,
    TraceEvent,
)

from .artifacts import ArtifactStore, sha256_file
from .sqlite import TABLE_ORDER
from .trace import replay_unique


def _load(path: Path, contract):
    return contract.model_validate_json(path.read_bytes())


def _relative(store: ArtifactStore, path: Path) -> str:
    return store.relative(path)


def _artifact_hash(path: Path) -> str:
    if not path.is_file():
        raise ValueError(f"referenced artifact does not exist: {path}")
    return sha256_file(path)


def _investigation_status(base: Path, output_root: Path) -> tuple[str, str | None]:
    review_path = base / "review/canonical.json"
    report_path = output_root / base.name / "report.md"
    review = _load(review_path, ReviewRecord) if review_path.is_file() else None
    if report_path.is_file():
        status = (
            "complete_with_warnings"
            if review is not None and review.report_status == "ready_with_warnings"
            else "complete"
        )
        return status, None
    if review is not None:
        return ("review_blocked" if review.report_status == "blocked" else "rendering"), None
    if any((base / "runs").glob("*/input.json")):
        review_tasks = [
            path
            for path in (base / "runs").glob("*/input.json")
            if json.loads(path.read_text(encoding="utf-8")).get("job_type")
            == "corpus_review"
        ]
        if review_tasks:
            return "reviewing", None
    if (base / "corpus.json").is_file():
        has_analysis = any((base / "papers").glob("**/canonical.json")) or any(
            (base / "paper-state").glob("*.json")
        )
        return ("analyzing" if has_analysis else "corpus_frozen"), None
    if any((base / "screening").glob("**/canonical.json")):
        return "screening", None
    if (base / "discovery/candidates.json").is_file():
        return "candidates_frozen", None
    return "inputs_validated", None


def project_repository(repository_root: Path | str) -> dict[str, list[dict[str, Any]]]:
    """Return a complete dependency-ordered projection of validated artifacts.

    This function never repairs or invents evidence. A malformed artifact,
    missing trace binding, or hash mismatch aborts the rebuild.
    """

    store = ArtifactStore(repository_root)
    rows: dict[str, list[dict[str, Any]]] = {table: [] for table in TABLE_ORDER}
    data_root = store.resolve("data")
    investigation_root = data_root / "investigations"
    output_root = store.resolve("out")

    identities: dict[str, tuple[PaperIdentity, Path]] = {}
    for path in sorted((data_root / "papers").glob("*/identity.json")):
        identity = _load(path, PaperIdentity)
        if identity.paper_id in identities:
            raise ValueError(f"duplicate paper identity: {identity.paper_id}")
        identities[identity.paper_id] = (identity, path)
        rows["papers"].append(
            {
                "paper_id": identity.paper_id,
                "schema_version": identity.schema_version,
                "title": identity.title,
                "authors_json": identity.authors,
                "published": identity.published,
                "identity_status": identity.identity_status,
                "identity_path": _relative(store, path),
                "identity_hash": identity.identity_hash,
            }
        )
        for identifier in identity.identifiers:
            rows["paper_identifiers"].append(
                {
                    "paper_id": identity.paper_id,
                    "scheme": identifier.scheme,
                    "value": identifier.value,
                    "url": identifier.url,
                }
            )

    source_by_paper: dict[str, list[SourcePacket]] = defaultdict(list)
    for path in sorted((data_root / "papers").glob("*/sources/*/source-packet.json")):
        packet = _load(path, SourcePacket)
        if packet.paper_id not in identities:
            raise ValueError(f"source packet has no paper identity: {packet.paper_id}")
        packet.validate_normalized_text(
            store.resolve(packet.normalized_path).read_text(encoding="utf-8")
        )
        if _artifact_hash(store.resolve(packet.original_path)) != packet.original_sha256:
            raise ValueError(f"source original hash mismatch: {packet.original_path}")
        source_by_paper[packet.paper_id].append(packet)
        rows["source_documents"].append(
            {
                "source_document_id": packet.source_document_id,
                "paper_id": packet.paper_id,
                "status": "frozen",
                "format": packet.format,
                "retrieval_method": packet.retrieval_method,
                "source_url": packet.source_url,
                "packet_path": _relative(store, path),
                "packet_hash": packet.packet_hash,
                "original_path": packet.original_path,
                "original_sha256": packet.original_sha256,
                "normalized_path": packet.normalized_path,
                "normalized_sha256": packet.normalized_sha256,
                "retrieved_at": packet.retrieved_at,
                "error": None,
            }
        )

    trace_by_run: dict[str, list[TraceEvent]] = defaultdict(list)
    for value in replay_unique(store.resolve("logs/trace.jsonl")):
        event = TraceEvent.model_validate(value)
        trace_by_run[event.agent_run_id].append(event)

    profiles: dict[str, dict[str, Any]] = {}
    plans: dict[str, dict[str, Any]] = {}
    completed_by_investigation: dict[str, str] = {}

    for base in sorted(path for path in investigation_root.glob("*") if path.is_dir()):
        spec_path = base / "investigation.json"
        profile_path = base / "objective-profile.json"
        plan_path = base / "search-plan.json"
        if not (spec_path.is_file() and profile_path.is_file() and plan_path.is_file()):
            raise ValueError(f"incomplete frozen investigation inputs: {base.name}")
        spec = _load(spec_path, InvestigationSpec)
        profile = _load(profile_path, ObjectiveProfile)
        plan = _load(plan_path, SearchPlan)
        if spec.investigation_id != base.name:
            raise ValueError("investigation directory does not match investigation_id")
        if profile.component != plan.component:
            raise ValueError("objective profile and search plan components do not match")

        global_profile_path = data_root / "objective-profiles" / f"{profile.profile_hash}.json"
        global_plan_path = data_root / "search-plans" / f"{plan.search_plan_hash}.json"
        if _load(global_profile_path, ObjectiveProfile) != profile:
            raise ValueError("global objective profile snapshot differs from investigation input")
        if _load(global_plan_path, SearchPlan) != plan:
            raise ValueError("global search-plan snapshot differs from investigation input")

        profile_row = profiles.setdefault(
            profile.profile_hash,
            {
                "profile_hash": profile.profile_hash,
                "profile_id": profile.profile_id,
                "schema_version": profile.schema_version,
                "component": profile.component,
                "origin": profile.origin,
                "artifact_path": _relative(store, global_profile_path),
                "created_at": spec.created_at,
            },
        )
        profile_row["created_at"] = min(profile_row["created_at"], spec.created_at)
        plan_row = plans.setdefault(
            plan.search_plan_hash,
            {
                "search_plan_hash": plan.search_plan_hash,
                "search_plan_id": plan.search_plan_id,
                "schema_version": plan.schema_version,
                "component": plan.component,
                "artifact_path": _relative(store, global_plan_path),
                "created_at": spec.created_at,
            },
        )
        plan_row["created_at"] = min(plan_row["created_at"], spec.created_at)

        corpus_path = base / "corpus.json"
        corpus = _load(corpus_path, CorpusManifest) if corpus_path.is_file() else None
        status, completed_at = _investigation_status(base, output_root)
        rows["investigations"].append(
            {
                "investigation_id": spec.investigation_id,
                "schema_version": spec.schema_version,
                "kind": spec.kind,
                "question": spec.question,
                "status": status,
                "spec_path": _relative(store, spec_path),
                "spec_hash": spec.spec_hash,
                "profile_hash": profile.profile_hash,
                "search_plan_hash": plan.search_plan_hash,
                "corpus_path": _relative(store, corpus_path) if corpus else None,
                "corpus_hash": corpus.corpus_hash if corpus else None,
                "created_at": spec.created_at,
                "completed_at": completed_at,
            }
        )

        candidates_path = base / "discovery/candidates.json"
        if candidates_path.is_file():
            candidates = _load(candidates_path, CandidateSet)
            if candidates.investigation_id != spec.investigation_id:
                raise ValueError("candidate set investigation binding mismatch")
            if candidates.search_plan_hash != plan.search_plan_hash:
                raise ValueError("candidate set search-plan binding mismatch")
            for candidate_index, candidate in enumerate(candidates.candidates):
                paper_id = candidate.paper_identity.paper_id
                if paper_id not in identities:
                    raise ValueError(f"candidate has no frozen paper identity: {paper_id}")
                if identities[paper_id][0] != candidate.paper_identity:
                    raise ValueError(f"candidate paper identity differs from frozen identity: {paper_id}")
                rows["candidate_papers"].append(
                    {
                        "investigation_id": spec.investigation_id,
                        "paper_id": paper_id,
                        "candidate_index": candidate_index,
                        "candidate_hash": candidate.candidate_hash,
                        "abstract": candidate.abstract,
                        "discovery_refs_json": candidate.discovery_refs,
                    }
                )

        states: dict[str, tuple[PaperStateRecord, Path]] = {}
        for path in sorted((base / "paper-state").glob("*.json")):
            state = _load(path, PaperStateRecord)
            if state.investigation_id != spec.investigation_id or path.stem != state.paper_id:
                raise ValueError("paper-state path or investigation binding mismatch")
            states[state.paper_id] = (state, path)

        if corpus is not None:
            if corpus.investigation_id != spec.investigation_id:
                raise ValueError("corpus investigation binding mismatch")
            if corpus.search_plan_hash != plan.search_plan_hash:
                raise ValueError("corpus search-plan binding mismatch")
            for entry in corpus.entries:
                state_item = states.get(entry.paper_id)
                state = state_item[0] if state_item else None
                if entry.membership_status != "included" and state is not None:
                    raise ValueError("non-included corpus entry cannot have a paper terminal state")
                rows["corpus_membership"].append(
                    {
                        "investigation_id": spec.investigation_id,
                        "paper_id": entry.paper_id,
                        "ordinal": entry.ordinal,
                        "membership_status": entry.membership_status,
                        "terminal_state": state.terminal_state if state else None,
                        "source_document_id": state.source_document_id if state else None,
                        "inclusion_reason": entry.inclusion_reason,
                        "exclusion_reason": entry.exclusion_reason,
                        "state_path": _relative(store, state_item[1]) if state_item else None,
                    }
                )

        run_rows, terminal_times = _project_runs(store, base, trace_by_run)
        rows["agent_runs"].extend(run_rows)
        completed_by_investigation.update(terminal_times)

        for path in sorted((base / "screening").glob("**/canonical.json")):
            record = _load(path, ScreeningRecord)
            artifact_hash = _artifact_hash(path)
            rows["screening_records"].append(
                {
                    "investigation_id": record.investigation_id,
                    "screening_batch_id": record.screening_batch_id,
                    "agent_run_id": record.agent_run_id,
                    "candidate_set_hash": record.candidate_set_hash,
                    "objective_profile_hash": record.objective_profile_hash,
                    "screening_scope_hash": record.screening_scope_hash,
                    "input_hash": record.input_hash,
                    "artifact_path": _relative(store, path),
                    "artifact_hash": artifact_hash,
                }
            )
            for decision in record.decisions:
                rows["screening_decisions"].append(
                    {
                        "investigation_id": record.investigation_id,
                        "screening_batch_id": record.screening_batch_id,
                        "paper_id": decision.paper_id,
                        "candidate_hash": decision.candidate_hash,
                        "state": decision.state,
                        "reason": decision.reason,
                        "evidence_spans_json": [
                            item.model_dump(mode="json") for item in decision.evidence_spans
                        ],
                    }
                )

        reader_ids: dict[str, str] = {}
        for path in sorted((base / "papers").glob("*/reader/canonical.json")):
            record = _load(path, ReaderRecord)
            record_id = f"reader-{record.agent_run_id}"
            reader_ids[record.agent_run_id] = record_id
            rows["reader_records"].append(
                {
                    "reader_record_id": record_id,
                    "agent_run_id": record.agent_run_id,
                    "investigation_id": record.investigation_id,
                    "paper_id": record.paper_id,
                    "source_document_id": record.source_document_id,
                    "input_hash": record.input_hash,
                    "artifact_path": _relative(store, path),
                    "artifact_hash": _artifact_hash(path),
                }
            )
            for claim_index, claim in enumerate(record.claims):
                locator = claim.source_locator
                rows["claims"].append(
                    {
                        "reader_record_id": record_id,
                        "claim_id": claim.claim_id,
                        "claim_index": claim_index,
                        "claim_kind": claim.claim_kind,
                        "text": claim.text,
                        "document_sha256": locator.document_sha256 if locator else None,
                        "section_id": locator.section_id if locator else None,
                        "start_char": locator.start_char if locator else None,
                        "end_char": locator.end_char if locator else None,
                        "source_quote": locator.quote if locator else None,
                        "evidence_modality": claim.evidence_modality,
                        "execution_environment": claim.execution_environment,
                        "provenance": claim.provenance,
                    }
                )

        for path in sorted((base / "papers").glob("*/critic/canonical.json")):
            record = _load(path, CriticRecord)
            reader_id = reader_ids.get(record.reader_run_id)
            if reader_id is None:
                raise ValueError("critic record has no canonical reader record")
            record_id = f"critic-{record.agent_run_id}"
            rows["critic_records"].append(
                {
                    "critic_record_id": record_id,
                    "agent_run_id": record.agent_run_id,
                    "investigation_id": record.investigation_id,
                    "paper_id": record.paper_id,
                    "reader_record_id": reader_id,
                    "input_hash": record.input_hash,
                    "artifact_path": _relative(store, path),
                    "artifact_hash": _artifact_hash(path),
                }
            )
            for verdict in record.verdicts:
                rows["verdicts"].append(
                    {
                        "critic_record_id": record_id,
                        "reader_record_id": reader_id,
                        "claim_id": verdict.claim_id,
                        "status": verdict.status,
                        "evidence_classification_correct": verdict.evidence_classification_correct,
                        "reason": verdict.reason,
                    }
                )
            for assessment in record.objective_assessments:
                rows["objective_assessments"].append(
                    {
                        "critic_record_id": record_id,
                        "criterion_id": assessment.criterion_id,
                        "score": assessment.score,
                        "reason": assessment.reason,
                        "assumptions_json": assessment.assumptions,
                        "uncertain": assessment.uncertain,
                    }
                )
                for claim_id in assessment.evidence_claim_ids:
                    rows["assessment_evidence"].append(
                        {
                            "critic_record_id": record_id,
                            "criterion_id": assessment.criterion_id,
                            "reader_record_id": reader_id,
                            "claim_id": claim_id,
                        }
                    )

        review_path = base / "review/canonical.json"
        if review_path.is_file():
            record = _load(review_path, ReviewRecord)
            record_id = f"review-{record.agent_run_id}"
            rows["review_records"].append(
                {
                    "review_record_id": record_id,
                    "agent_run_id": record.agent_run_id,
                    "investigation_id": record.investigation_id,
                    "input_hash": record.input_hash,
                    "report_status": record.report_status,
                    "artifact_path": _relative(store, review_path),
                    "artifact_hash": _artifact_hash(review_path),
                }
            )
            for finding in record.findings:
                rows["review_findings"].append(
                    {
                        "review_record_id": record_id,
                        "finding_id": finding.finding_id,
                        "text": finding.text,
                        "provenance": finding.provenance,
                        "uncertain": finding.uncertain,
                    }
                )
                for ref in finding.evidence_refs:
                    evidence_id = getattr(ref, "claim_id", None) or getattr(
                        ref, "criterion_id", None
                    ) or "corpus-entry"
                    rows["review_evidence"].append(
                        {
                            "review_record_id": record_id,
                            "finding_id": finding.finding_id,
                            "evidence_type": ref.kind,
                            "paper_id": ref.paper_id,
                            "evidence_id": evidence_id,
                        }
                    )

    rows["objective_profiles"] = list(profiles.values())
    rows["search_plans"] = list(plans.values())
    for row in rows["investigations"]:
        if row["status"] in {"complete", "complete_with_warnings"}:
            row["completed_at"] = completed_by_investigation.get(row["investigation_id"])
    return rows


def _project_runs(
    store: ArtifactStore,
    investigation_base: Path,
    trace_by_run: dict[str, list[TraceEvent]],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    result: list[dict[str, Any]] = []
    completed: dict[str, str] = {}
    for run_dir in sorted(path for path in (investigation_base / "runs").glob("*") if path.is_dir()):
        events = trace_by_run.get(run_dir.name, [])
        if not events:
            if (run_dir / "outcome.json").exists():
                raise ValueError(f"run outcome has no trace events: {run_dir.name}")
            continue
        events.sort(key=lambda item: item.sequence)
        first = events[0]
        if first.event_type != "agent_run.started":
            raise ValueError(f"run does not begin with a start event: {run_dir.name}")
        for event in events:
            fields = (
                "investigation_id",
                "paper_id",
                "screening_batch_id",
                "role",
                "job_type",
                "attempt_no",
                "model",
                "agent_definition_hash",
                "component_skill_hash",
                "objective_profile_hash",
                "input_path",
                "input_hash",
            )
            if any(getattr(event, name) != getattr(first, name) for name in fields):
                raise ValueError(f"run trace immutable fields changed: {run_dir.name}")
        outcome_path = run_dir / "outcome.json"
        if outcome_path.is_file():
            outcome = _load(outcome_path, OutcomeRecord)
            if outcome.agent_run_id != run_dir.name or outcome.input_hash != first.input_hash:
                raise ValueError(f"run outcome binding mismatch: {run_dir.name}")
            row = {
                "agent_run_id": run_dir.name,
                "investigation_id": first.investigation_id,
                "paper_id": first.paper_id,
                "screening_batch_id": first.screening_batch_id,
                "role": first.role,
                "job_type": first.job_type,
                "attempt_no": first.attempt_no,
                "status": outcome.status,
                "model": first.model,
                "agent_definition_hash": first.agent_definition_hash,
                "component_skill_hash": first.component_skill_hash,
                "objective_profile_hash": first.objective_profile_hash,
                "input_path": outcome.input_path,
                "input_hash": outcome.input_hash,
                "raw_output_path": outcome.raw_output_path,
                "raw_output_hash": outcome.raw_output_hash,
                "validation_path": outcome.validation_path,
                "validation_hash": outcome.validation_hash,
                "canonical_path": outcome.canonical_path,
                "canonical_hash": outcome.canonical_hash,
                "started_at": outcome.started_at,
                "completed_at": outcome.completed_at,
                "duration_ms": outcome.duration_ms,
                "tokens_in": outcome.tokens_in,
                "tokens_out": outcome.tokens_out,
                "cost_usd": outcome.cost_usd,
                "error": outcome.error,
            }
            AgentRun.model_validate({"schema_version": "2.0", **row})
            result.append(row)
            if first.role == "reviewer" and outcome.status == "completed":
                completed[first.investigation_id] = outcome.completed_at
        else:
            result.append(
                {
                    "agent_run_id": run_dir.name,
                    "investigation_id": first.investigation_id,
                    "paper_id": first.paper_id,
                    "screening_batch_id": first.screening_batch_id,
                    "role": first.role,
                    "job_type": first.job_type,
                    "attempt_no": first.attempt_no,
                    "status": "running",
                    "model": first.model,
                    "agent_definition_hash": first.agent_definition_hash,
                    "component_skill_hash": first.component_skill_hash,
                    "objective_profile_hash": first.objective_profile_hash,
                    "input_path": first.input_path,
                    "input_hash": first.input_hash,
                    "raw_output_path": None,
                    "raw_output_hash": None,
                    "validation_path": None,
                    "validation_hash": None,
                    "canonical_path": None,
                    "canonical_hash": None,
                    "started_at": first.timestamp,
                    "completed_at": None,
                    "duration_ms": None,
                    "tokens_in": None,
                    "tokens_out": None,
                    "cost_usd": None,
                    "error": None,
                }
            )
    return result, completed


__all__ = ["project_repository"]
