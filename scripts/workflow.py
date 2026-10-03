#!/usr/bin/env python3
"""Thin deterministic CLI for schema-2.0 investigation workflow operations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arxiv_triage.dispatch import DispatchResult, RunContext, RunExecutor  # noqa: E402
from arxiv_triage.models import (  # noqa: E402
    CandidateSet,
    CorpusManifest,
    CriticRecord,
    CriticRubric,
    CriticTask,
    InvestigationSpec,
    ObjectiveProfile,
    OutcomeRecord,
    PaperIdentity,
    PaperStateRecord,
    ReaderFocus,
    ReaderRecord,
    ReaderTask,
    ReviewPaper,
    ReviewerRubric,
    ReviewerTask,
    ScreeningRecord,
    ScreeningScope,
    ScreeningTask,
    SearchPlan,
    SourcePacket,
    sha256_bytes,
    sha256_json,
    validate_critic_output,
    validate_reader_output,
    validate_reviewer_output,
    validate_screening_output,
)
from arxiv_triage.storage import ArtifactStore  # noqa: E402
from arxiv_triage.workflow import (  # noqa: E402
    InvestigationState,
    WorkflowService,
    analysis_status,
    prepare_critic_task,
    prepare_reader_task,
    prepare_reviewer_task,
    prepare_screening_task,
    route_authoritative_membership,
    route_screening_records,
)


AGENT_FILES = {
    "paper_screen": ".claude/agents/paper-screener.md",
    "paper_read": ".claude/agents/paper-reader.md",
    "paper_critique": ".claude/agents/critic.md",
    "corpus_review": ".claude/agents/reviewer.md",
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_model(path: Path, contract):
    return contract.model_validate(load_json(path))


def investigation_root(root: Path, investigation_id: str) -> Path:
    return root / "data" / "investigations" / investigation_id


def paper_state_path(investigation_id: str, paper_id: str) -> str:
    return f"data/investigations/{investigation_id}/paper-state/{paper_id}.json"


def _paper_state(
    *,
    investigation_id: str,
    paper_id: str,
    terminal_state: str,
    source_document_id: str | None,
    reader_run_id: str | None,
    critic_run_id: str | None,
    error: str | None,
    completed_at: str,
) -> PaperStateRecord:
    payload = {
        "schema_version": "2.0",
        "investigation_id": investigation_id,
        "paper_id": paper_id,
        "terminal_state": terminal_state,
        "source_document_id": source_document_id,
        "reader_run_id": reader_run_id,
        "critic_run_id": critic_run_id,
        "error": error,
        "completed_at": completed_at,
    }
    payload["state_hash"] = sha256_json(payload)
    return PaperStateRecord.model_validate(payload)


def _included_entry(root: Path, investigation_id: str, paper_id: str) -> None:
    corpus = load_model(
        investigation_root(root, investigation_id) / "corpus.json", CorpusManifest
    )
    matches = [entry for entry in corpus.entries if entry.paper_id == paper_id]
    if len(matches) != 1 or matches[0].membership_status != "included":
        raise ValueError("paper must be an included member of the frozen corpus")


def input_models(root: Path, investigation_id: str):
    base = investigation_root(root, investigation_id)
    return (
        load_model(base / "investigation.json", InvestigationSpec),
        load_model(base / "objective-profile.json", ObjectiveProfile),
        load_model(base / "search-plan.json", SearchPlan),
    )


def cmd_create(args: argparse.Namespace) -> dict[str, Any]:
    spec = load_model(args.spec, InvestigationSpec)
    profile = load_model(args.profile, ObjectiveProfile)
    plan = load_model(args.search_plan, SearchPlan)
    if profile.component != plan.component:
        raise ValueError("objective profile and search plan components do not match")
    WorkflowService.create_investigation(inputs_valid=True)
    store = ArtifactStore(args.root)
    base = f"data/investigations/{spec.investigation_id}"
    store.write_json(f"{base}/investigation.json", spec)
    store.write_json(f"{base}/objective-profile.json", profile)
    store.write_json(f"{base}/search-plan.json", plan)
    store.write_json(f"data/objective-profiles/{profile.profile_hash}.json", profile)
    store.write_json(f"data/search-plans/{plan.search_plan_hash}.json", plan)
    return {"investigation_id": spec.investigation_id, "state": "inputs_validated"}


def cmd_status(args: argparse.Namespace) -> dict[str, Any]:
    base = investigation_root(args.root, args.investigation_id)
    if not base.exists():
        return {"investigation_id": args.investigation_id, "state": "draft", "exists": False}
    review_path = base / "review/canonical.json"
    report_path = args.root / "out" / args.investigation_id / "report.md"
    exhausted_screening = False
    for outcome_path in (base / "runs").glob("*/outcome.json"):
        outcome = load_json(outcome_path)
        if outcome.get("status") not in {"invalid", "failed"}:
            continue
        task_path = outcome_path.with_name("input.json")
        if task_path.is_file():
            task = load_json(task_path)
            exhausted_screening = (
                task.get("job_type") == "paper_screen"
                and task.get("agent_run_id") == outcome.get("agent_run_id")
            )
            if exhausted_screening:
                # The bounded retry number lives in the lifecycle trace. The
                # second-attempt task is conventionally accepted with --attempt 2;
                # outcome alone intentionally does not duplicate it.
                trace_path = args.root / "logs/trace.jsonl"
                if trace_path.is_file():
                    exhausted_screening = any(
                        json.loads(line).get("agent_run_id") == outcome["agent_run_id"]
                        and json.loads(line).get("attempt_no") == 2
                        for line in trace_path.read_text(encoding="utf-8").splitlines()
                    )
            if exhausted_screening:
                break
    if exhausted_screening:
        state = "failed"
    elif report_path.is_file():
        state = "complete"
    elif review_path.is_file():
        review = load_json(review_path)
        state = "review_blocked" if review.get("report_status") == "blocked" else "rendering"
    elif (base / "corpus.json").is_file():
        state = "analyzing"
    elif any((base / "screening").glob("**/canonical.json")):
        state = "screening"
    elif (base / "discovery/candidates.json").is_file():
        state = "candidates_frozen"
    else:
        state = "inputs_validated"
    return {"investigation_id": args.investigation_id, "state": state, "exists": True}


def cmd_freeze_candidates(args: argparse.Namespace) -> dict[str, Any]:
    _spec, _profile, plan = input_models(args.root, args.investigation_id)
    candidates = load_model(args.candidate_set, CandidateSet)
    scope = load_model(args.screening_scope, ScreeningScope)
    if candidates.investigation_id != args.investigation_id:
        raise ValueError("candidate set investigation_id does not match")
    if candidates.search_plan_hash != plan.search_plan_hash:
        raise ValueError("candidate set search_plan_hash does not match")
    WorkflowService.freeze_candidates(
        InvestigationState.DISCOVERING,
        search_completion_satisfied=args.search_complete,
        candidate_set_valid=True,
    )
    store = ArtifactStore(args.root)
    store.write_json(
        store.candidate_set_path(args.investigation_id), candidates
    )
    store.write_json(
        f"data/investigations/{args.investigation_id}/screening-scope.json", scope
    )
    for candidate in candidates.candidates:
        store.write_json(
            f"data/papers/{candidate.paper_identity.paper_id}/identity.json",
            candidate.paper_identity,
        )
    return {"state": "candidates_frozen", "candidates": len(candidates.candidates)}


def cmd_prepare_screening(args: argparse.Namespace) -> dict[str, Any]:
    _spec, profile, _plan = input_models(args.root, args.investigation_id)
    base = investigation_root(args.root, args.investigation_id)
    candidates = load_model(base / "discovery/candidates.json", CandidateSet)
    scope = load_model(base / "screening-scope.json", ScreeningScope)
    if args.batch_size < 1:
        raise ValueError("batch size must be positive")
    WorkflowService.begin_screening(InvestigationState.CANDIDATES_FROZEN)
    batches = (len(candidates.candidates) + args.batch_size - 1) // args.batch_size
    store = ArtifactStore(args.root)
    paths: list[str] = []
    for ordinal in range(1, batches + 1):
        task = prepare_screening_task(
            candidate_set=candidates,
            objective_profile=profile,
            screening_scope=scope,
            batch_ordinal=ordinal,
            batch_size_limit=args.batch_size,
            agent_run_id=f"{args.agent_run_prefix}-{ordinal:04d}",
        )
        path = store.run_bundle(args.investigation_id, task.agent_run_id).input
        store.write_json(path, task)
        paths.append(path)
    return {"state": "screening", "batches": batches, "task_paths": paths}


def _source_packet(root: Path, paper_id: str, explicit: Path | None) -> tuple[SourcePacket, str]:
    if explicit is None:
        matches = sorted((root / "data/papers" / paper_id / "sources").glob("*/source-packet.json"))
        if len(matches) != 1:
            raise ValueError("exactly one source packet must exist or --source-packet is required")
        explicit = matches[0]
    packet = load_model(explicit, SourcePacket)
    text = (root / packet.normalized_path).read_text(encoding="utf-8")
    packet.validate_normalized_text(text)
    return packet, text


def cmd_prepare_reader(args: argparse.Namespace) -> dict[str, Any]:
    _included_entry(args.root, args.investigation_id, args.paper_id)
    paper = load_model(args.root / f"data/papers/{args.paper_id}/identity.json", PaperIdentity)
    packet, text = _source_packet(args.root, args.paper_id, args.source_packet)
    focus = load_model(args.focus, ReaderFocus)
    task = prepare_reader_task(
        agent_run_id=args.agent_run_id,
        investigation_id=args.investigation_id,
        paper_identity=paper,
        source_packet=packet,
        source_text=text,
        focus=focus,
    )
    path = ArtifactStore(args.root).run_bundle(args.investigation_id, args.agent_run_id).input
    ArtifactStore(args.root).write_json(path, task)
    return {"task_path": path, "paper_id": args.paper_id}


def cmd_prepare_critic(args: argparse.Namespace) -> dict[str, Any]:
    _included_entry(args.root, args.investigation_id, args.paper_id)
    _spec, profile, _plan = input_models(args.root, args.investigation_id)
    paper = load_model(args.root / f"data/papers/{args.paper_id}/identity.json", PaperIdentity)
    packet, text = _source_packet(args.root, args.paper_id, args.source_packet)
    reader_path = investigation_root(args.root, args.investigation_id) / f"papers/{args.paper_id}/reader/canonical.json"
    reader = load_model(reader_path, ReaderRecord)
    rubric = load_model(args.rubric, CriticRubric)
    task = prepare_critic_task(
        agent_run_id=args.agent_run_id,
        investigation_id=args.investigation_id,
        paper_identity=paper,
        source_packet=packet,
        source_text=text,
        reader_record=reader,
        objective_profile=profile,
        critic_rubric=rubric,
    )
    path = ArtifactStore(args.root).run_bundle(args.investigation_id, args.agent_run_id).input
    ArtifactStore(args.root).write_json(path, task)
    return {"task_path": path, "paper_id": args.paper_id}


def cmd_prepare_reviewer(args: argparse.Namespace) -> dict[str, Any]:
    spec, profile, plan = input_models(args.root, args.investigation_id)
    base = investigation_root(args.root, args.investigation_id)
    corpus = load_model(base / "corpus.json", CorpusManifest)
    if args.papers:
        papers = [ReviewPaper.model_validate(item) for item in load_json(args.papers)]
    else:
        papers = []
        for entry in corpus.entries:
            if entry.membership_status != "included":
                continue
            state = load_model(
                base / f"paper-state/{entry.paper_id}.json", PaperStateRecord
            )
            reader_path = base / f"papers/{entry.paper_id}/reader/canonical.json"
            critic_path = base / f"papers/{entry.paper_id}/critic/canonical.json"
            reader_record = (
                load_model(reader_path, ReaderRecord) if reader_path.is_file() else None
            )
            critic_record = (
                load_model(critic_path, CriticRecord) if critic_path.is_file() else None
            )
            papers.append(
                ReviewPaper(
                    paper_id=entry.paper_id,
                    analysis_status=state.terminal_state,
                    reader_record=reader_record,
                    critic_record=critic_record,
                )
            )
    rubric = load_model(args.rubric, ReviewerRubric)
    ranking_path = args.ranking or base / "ranking.json"
    ranking = load_json(ranking_path) if ranking_path.is_file() else None
    task = prepare_reviewer_task(
        agent_run_id=args.agent_run_id,
        investigation_spec=spec,
        objective_profile=profile,
        search_plan=plan,
        corpus_manifest=corpus,
        papers=papers,
        ranking_artifact=ranking,
        reviewer_rubric=rubric,
    )
    path = ArtifactStore(args.root).run_bundle(args.investigation_id, args.agent_run_id).input
    ArtifactStore(args.root).write_json(path, task)
    return {"task_path": path, "papers": len(papers)}


class _FileDispatcher:
    def __init__(self, path: Path) -> None:
        self.path = path

    def dispatch(self, task) -> DispatchResult:
        del task
        return DispatchResult(self.path.read_bytes())


def cmd_accept_run(args: argparse.Namespace) -> dict[str, Any]:
    task_value = load_json(args.task)
    job_type = task_value.get("job_type")
    contracts = {
        "paper_screen": (ScreeningTask, validate_screening_output, "paper_screener"),
        "paper_read": (ReaderTask, validate_reader_output, "paper_reader"),
        "paper_critique": (CriticTask, validate_critic_output, "critic"),
        "corpus_review": (ReviewerTask, validate_reviewer_output, "reviewer"),
    }
    if job_type not in contracts:
        raise ValueError(f"unsupported task job_type: {job_type!r}")
    contract, validator, role = contracts[job_type]
    task = contract.model_validate(task_value)
    paper_id = task.paper_identity.paper_id if hasattr(task, "paper_identity") else None
    batch_id = getattr(task, "screening_batch_id", None)
    profile_hash = (
        task.objective_profile.profile_hash
        if hasattr(task, "objective_profile")
        else None
    )
    component_skill_hash = None
    for field_name in ("focus", "critic_rubric", "reviewer_rubric"):
        component_input = getattr(task, field_name, None)
        if component_input is not None:
            component_skill_hash = component_input.skill_hash
            break
    if job_type == "paper_screen":
        canonical = ArtifactStore.screening_record_path(
            task.investigation_id, profile_hash, batch_id
        )
    elif job_type in {"paper_read", "paper_critique"}:
        kind = "reader" if job_type == "paper_read" else "critic"
        canonical = f"data/investigations/{task.investigation_id}/papers/{paper_id}/{kind}/canonical.json"
    else:
        canonical = f"data/investigations/{task.investigation_id}/review/canonical.json"
    agent_file = args.agent_definition or args.root / AGENT_FILES[job_type]
    context = RunContext(
        investigation_id=task.investigation_id,
        paper_id=paper_id,
        screening_batch_id=batch_id,
        role=role,
        job_type=job_type,
        attempt_no=args.attempt,
        model=args.model,
        agent_definition_hash=sha256_bytes(agent_file.read_bytes()),
        component_skill_hash=component_skill_hash,
        objective_profile_hash=profile_hash,
        canonical_path=canonical,
    )
    result = RunExecutor(str(args.root)).execute(
        task=task,
        context=context,
        validator=validator,
        dispatcher=_FileDispatcher(args.raw_output),
    )
    if paper_id is not None:
        state: PaperStateRecord | None = None
        if job_type == "paper_critique" and result.canonical_record is not None:
            critic_record = CriticRecord.model_validate(result.canonical_record)
            state = _paper_state(
                investigation_id=task.investigation_id,
                paper_id=paper_id,
                terminal_state=analysis_status(critic_record),
                source_document_id=task.source_packet.source_document_id,
                reader_run_id=task.reader_record.agent_run_id,
                critic_run_id=critic_record.agent_run_id,
                error=None,
                completed_at=result.run.completed_at,
            )
        elif args.attempt == 2 and result.run.status in {"invalid", "failed"}:
            state = _paper_state(
                investigation_id=task.investigation_id,
                paper_id=paper_id,
                terminal_state="failed",
                source_document_id=task.source_packet.source_document_id,
                reader_run_id=(
                    task.reader_record.agent_run_id
                    if job_type == "paper_critique"
                    else None
                ),
                critic_run_id=None,
                error=result.run.error,
                completed_at=result.run.completed_at,
            )
        if state is not None:
            ArtifactStore(args.root).write_json(
                paper_state_path(task.investigation_id, paper_id), state
            )
    return {
        "agent_run_id": result.run.agent_run_id,
        "status": result.run.status,
        "canonical_path": result.run.canonical_path,
        "error": result.run.error,
    }


def cmd_sync_paper_state(args: argparse.Namespace) -> dict[str, Any]:
    """Recover a missing terminal paper-state from validated run artifacts."""

    task = load_model(args.task, CriticTask)
    outcome = load_model(args.outcome, OutcomeRecord)
    critic = load_model(args.canonical, CriticRecord)
    if outcome.status != "completed" or outcome.completed_at is None:
        raise ValueError("paper-state recovery requires a completed critic outcome")
    if outcome.agent_run_id != task.agent_run_id or critic.agent_run_id != task.agent_run_id:
        raise ValueError("task, outcome, and critic run IDs do not match")
    if outcome.input_hash != task.input_hash or critic.input_hash != task.input_hash:
        raise ValueError("task, outcome, and critic input hashes do not match")
    expected_canonical = (
        f"data/investigations/{task.investigation_id}/papers/"
        f"{task.paper_identity.paper_id}/critic/canonical.json"
    )
    if outcome.canonical_path != expected_canonical:
        raise ValueError("critic outcome canonical path is not the expected paper artifact")
    if ArtifactStore(args.root).relative(args.canonical) != expected_canonical:
        raise ValueError("supplied canonical path is not the expected paper artifact")
    state = _paper_state(
        investigation_id=task.investigation_id,
        paper_id=task.paper_identity.paper_id,
        terminal_state=analysis_status(critic),
        source_document_id=task.source_packet.source_document_id,
        reader_run_id=task.reader_record.agent_run_id,
        critic_run_id=critic.agent_run_id,
        error=None,
        completed_at=outcome.completed_at,
    )
    path = paper_state_path(task.investigation_id, task.paper_identity.paper_id)
    ArtifactStore(args.root).write_json(path, state)
    return {"paper_id": state.paper_id, "terminal_state": state.terminal_state, "path": path}


def cmd_mark_paper_failed(args: argparse.Namespace) -> dict[str, Any]:
    _included_entry(args.root, args.investigation_id, args.paper_id)
    state = _paper_state(
        investigation_id=args.investigation_id,
        paper_id=args.paper_id,
        terminal_state="failed",
        source_document_id=args.source_document_id,
        reader_run_id=args.reader_run_id,
        critic_run_id=None,
        error=args.error,
        completed_at=args.completed_at,
    )
    path = paper_state_path(args.investigation_id, args.paper_id)
    ArtifactStore(args.root).write_json(path, state)
    return {"paper_id": args.paper_id, "terminal_state": "failed", "state_path": path}


def cmd_freeze_corpus(args: argparse.Namespace) -> dict[str, Any]:
    _spec, profile, plan = input_models(args.root, args.investigation_id)
    base = investigation_root(args.root, args.investigation_id)
    candidates = load_model(base / "discovery/candidates.json", CandidateSet)
    if args.mode == "authoritative":
        routes = route_authoritative_membership(
            candidate_set=candidates, authoritative_membership=True
        )
        WorkflowService.freeze_authoritative_corpus(
            InvestigationState.CANDIDATES_FROZEN,
            authoritative_membership=True,
            membership_valid=True,
            counts_valid=True,
        )
    else:
        scope = load_model(base / "screening-scope.json", ScreeningScope)
        record_paths = sorted((base / "screening").glob("**/canonical.json"))
        records = [load_model(path, ScreeningRecord) for path in record_paths]
        routes = route_screening_records(
            candidate_set=candidates,
            objective_profile=profile,
            screening_scope=scope,
            records=records,
            identity_failure_paper_ids=args.identity_failure,
        )
        WorkflowService.freeze_screened_corpus(
            InvestigationState.SCREENING,
            screening_coverage_valid=True,
            membership_valid=True,
            counts_valid=True,
        )
    candidate_by_id = {
        item.paper_identity.paper_id: item for item in candidates.candidates
    }
    entries = [
        {
            "ordinal": ordinal,
            "paper_id": route.paper_id,
            "membership_status": route.membership_status,
            "discovery_refs": candidate_by_id[route.paper_id].discovery_refs,
            "inclusion_reason": route.inclusion_reason,
            "exclusion_reason": route.exclusion_reason,
            "terminal_state": None,
        }
        for ordinal, route in enumerate(routes, start=1)
    ]
    payload: dict[str, Any] = {
        "schema_version": "2.0",
        "investigation_id": args.investigation_id,
        "search_plan_hash": plan.search_plan_hash,
        "frozen_at": args.frozen_at,
        "entries": entries,
        "counts": {
            "discovered": len(entries),
            "included": sum(item["membership_status"] == "included" for item in entries),
            "excluded": sum(item["membership_status"] == "excluded" for item in entries),
            "membership_unresolved": sum(
                item["membership_status"] == "membership_unresolved" for item in entries
            ),
        },
    }
    payload["corpus_hash"] = sha256_json(payload)
    corpus = CorpusManifest.model_validate(payload)
    ArtifactStore(args.root).write_json(
        f"data/investigations/{args.investigation_id}/corpus.json", corpus
    )
    return {"state": "corpus_frozen", "counts": corpus.counts.model_dump()}


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(description=__doc__)
    top.add_argument("--root", type=Path, default=ROOT)
    sub = top.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create")
    create.add_argument("--spec", type=Path, required=True)
    create.add_argument("--profile", type=Path, required=True)
    create.add_argument("--search-plan", type=Path, required=True)
    create.set_defaults(func=cmd_create)

    status = sub.add_parser("status")
    status.add_argument("investigation_id")
    status.set_defaults(func=cmd_status)

    freeze = sub.add_parser("freeze-candidates")
    freeze.add_argument("investigation_id")
    freeze.add_argument("--candidate-set", type=Path, required=True)
    freeze.add_argument("--screening-scope", type=Path, required=True)
    freeze.add_argument("--search-complete", action="store_true")
    freeze.set_defaults(func=cmd_freeze_candidates)

    screen = sub.add_parser("prepare-screening")
    screen.add_argument("investigation_id")
    screen.add_argument("--batch-size", type=int, required=True)
    screen.add_argument("--agent-run-prefix", default="run-screening")
    screen.set_defaults(func=cmd_prepare_screening)

    accept = sub.add_parser("accept-run")
    accept.add_argument("--task", type=Path, required=True)
    accept.add_argument("--raw-output", type=Path, required=True)
    accept.add_argument("--attempt", type=int, default=1)
    accept.add_argument("--model", required=True)
    accept.add_argument("--agent-definition", type=Path)
    accept.set_defaults(func=cmd_accept_run)

    sync_state = sub.add_parser("sync-paper-state")
    sync_state.add_argument("--task", type=Path, required=True)
    sync_state.add_argument("--outcome", type=Path, required=True)
    sync_state.add_argument("--canonical", type=Path, required=True)
    sync_state.set_defaults(func=cmd_sync_paper_state)

    corpus = sub.add_parser("freeze-corpus")
    corpus.add_argument("investigation_id")
    corpus.add_argument("--mode", choices=["semantic", "authoritative"], required=True)
    corpus.add_argument("--identity-failure", action="append", default=[])
    corpus.add_argument("--frozen-at", required=True)
    corpus.set_defaults(func=cmd_freeze_corpus)

    reader = sub.add_parser("prepare-reader")
    reader.add_argument("investigation_id")
    reader.add_argument("paper_id")
    reader.add_argument("--agent-run-id", required=True)
    reader.add_argument("--source-packet", type=Path)
    reader.add_argument("--focus", type=Path, required=True)
    reader.set_defaults(func=cmd_prepare_reader)

    critic = sub.add_parser("prepare-critic")
    critic.add_argument("investigation_id")
    critic.add_argument("paper_id")
    critic.add_argument("--agent-run-id", required=True)
    critic.add_argument("--source-packet", type=Path)
    critic.add_argument("--rubric", type=Path, required=True)
    critic.set_defaults(func=cmd_prepare_critic)

    reviewer = sub.add_parser("prepare-reviewer")
    reviewer.add_argument("investigation_id")
    reviewer.add_argument("--agent-run-id", required=True)
    reviewer.add_argument("--papers", type=Path)
    reviewer.add_argument("--ranking", type=Path)
    reviewer.add_argument("--rubric", type=Path, required=True)
    reviewer.set_defaults(func=cmd_prepare_reviewer)

    failed = sub.add_parser("mark-paper-failed")
    failed.add_argument("investigation_id")
    failed.add_argument("paper_id")
    failed.add_argument("--error", required=True)
    failed.add_argument("--completed-at", required=True)
    failed.add_argument("--source-document-id")
    failed.add_argument("--reader-run-id")
    failed.set_defaults(func=cmd_mark_paper_failed)
    return top


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result = args.func(args)
    except Exception as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
