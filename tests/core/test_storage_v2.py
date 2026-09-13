from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arxiv_triage.storage.artifacts import (  # noqa: E402
    ArtifactCollisionError,
    ArtifactStore,
    canonical_json_bytes,
    sha256_bytes,
)
from arxiv_triage.storage.reconcile import Reconciler  # noqa: E402
from arxiv_triage.storage.sqlite import (  # noqa: E402
    ProjectionConflictError,
    SQLiteIndex,
    StorageSchemaError,
    rebuild_index,
)
from arxiv_triage.storage.trace import TraceAppender, iter_trace, replay_unique  # noqa: E402
from arxiv_triage.models.run import (  # noqa: E402
    AgentRun,
    OutcomeRecord,
    TraceEvent,
    ValidationCheck,
    ValidationRecord,
)


HASH = "a" * 64


def event(run_id: str, event_type: str, sequence: int) -> dict[str, object]:
    return {
        "schema_version": "2.0",
        "event_id": f"evt-{run_id}-{event_type}-{sequence}",
        "event_type": event_type,
        "timestamp": "2026-09-12T18:10:00Z",
        "agent_run_id": run_id,
        "investigation_id": "inv-test",
        "paper_id": "paper-1",
        "role": "paper_reader",
        "job_type": "paper_read",
        "attempt_no": 1,
        "sequence": sequence,
        "model": "model-test",
        "agent_definition_hash": HASH,
        "component_skill_hash": None,
        "objective_profile_hash": HASH,
        "input_path": f"data/investigations/inv-test/runs/{run_id}/input.json",
        "input_hash": HASH,
        "artifact_path": None,
        "artifact_hash": None,
        "tokens_in": None,
        "tokens_out": None,
        "cost_usd": None,
        "error": None,
    }


def base_rows(*, include_run: bool = False) -> dict[str, list[dict[str, object]]]:
    rows: dict[str, list[dict[str, object]]] = {
        "objective_profiles": [
            {
                "profile_hash": HASH,
                "profile_id": "profile-test",
                "schema_version": "2.0",
                "component": "test",
                "origin": "user_authored",
                "artifact_path": f"data/objective-profiles/{HASH}.json",
                "created_at": "2026-09-12T18:00:00Z",
            }
        ],
        "search_plans": [
            {
                "search_plan_hash": HASH,
                "search_plan_id": "search-test",
                "schema_version": "2.0",
                "component": "test",
                "artifact_path": f"data/search-plans/{HASH}.json",
                "created_at": "2026-09-12T18:00:00Z",
            }
        ],
        "investigations": [
            {
                "investigation_id": "inv-test",
                "schema_version": "2.0",
                "kind": "test",
                "question": "Does storage preserve evidence?",
                "status": "analyzing",
                "spec_path": "data/investigations/inv-test/investigation.json",
                "spec_hash": HASH,
                "profile_hash": HASH,
                "search_plan_hash": HASH,
                "corpus_path": "data/investigations/inv-test/corpus.json",
                "corpus_hash": HASH,
                "created_at": "2026-09-12T18:00:00Z",
                "completed_at": None,
            }
        ],
        "papers": [
            {
                "paper_id": "paper-1",
                "schema_version": "2.0",
                "title": "Synthetic paper",
                "authors_json": '["A. Author"]',
                "published": None,
                "identity_status": "resolved_exact",
                "identity_path": "data/papers/paper-1/identity.json",
                "identity_hash": HASH,
            }
        ],
    }
    if include_run:
        rows["agent_runs"] = [agent_run_row("run-1")]
    return rows


def agent_run_row(run_id: str) -> dict[str, object]:
    return {
        "agent_run_id": run_id,
        "investigation_id": "inv-test",
        "paper_id": "paper-1",
        "role": "paper_reader",
        "job_type": "paper_read",
        "attempt_no": 1,
        "status": "running",
        "model": "model-test",
        "agent_definition_hash": HASH,
        "component_skill_hash": None,
        "objective_profile_hash": HASH,
        "input_path": f"data/investigations/inv-test/runs/{run_id}/input.json",
        "input_hash": HASH,
        "raw_output_path": None,
        "raw_output_hash": None,
        "validation_path": None,
        "validation_hash": None,
        "canonical_path": None,
        "canonical_hash": None,
        "started_at": "2026-09-12T18:10:00Z",
        "completed_at": None,
        "duration_ms": None,
        "tokens_in": None,
        "tokens_out": None,
        "cost_usd": None,
        "error": None,
    }


def test_canonical_json_and_hash_are_stable_and_unicode_preserving() -> None:
    first = canonical_json_bytes({"z": "µ", "a": [1, True]})
    second = canonical_json_bytes({"a": [1, True], "z": "µ"})
    assert first == second == b'{"a":[1,true],"z":"\xc2\xb5"}'
    assert sha256_bytes(first) == hashlib.sha256(first).hexdigest()


def test_artifact_writes_are_idempotent_and_collisions_are_visible(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    created = store.write_json("data/item.json", {"value": 1})
    repeated = store.write_json("data/item.json", {"value": 1})
    assert created.created is True
    assert repeated.created is False
    with pytest.raises(ArtifactCollisionError):
        store.write_json("data/item.json", {"value": 2})


def test_concurrent_artifact_creation_never_overwrites_first_writer(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path)

    def write(value: int) -> tuple[int, bool] | tuple[int, None]:
        try:
            created = store.write_json("data/shared.json", {"value": value}).created
        except ArtifactCollisionError:
            return value, None
        return value, created

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(write, range(8)))

    successful = [(value, created) for value, created in results if created is not None]
    assert len(successful) == 1
    winning_value, created = successful[0]
    assert created is True
    assert json.loads(store.resolve("data/shared.json").read_text()) == {
        "value": winning_value
    }


def test_run_bundle_accepts_exact_validation_and_outcome_models(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    bundle = store.run_bundle("inv-test", "run-invalid")
    validation = ValidationRecord(
        schema_version="2.0",
        agent_run_id="run-invalid",
        validator_version="core-v2-test",
        checked_at="2026-09-13T08:00:01Z",
        input_hash=HASH,
        parsed_hash=None,
        checks=[
            ValidationCheck(
                check_id="schema",
                status="failed",
                detail="missing required field",
            )
        ],
        errors=["missing required field"],
        referenced_hashes=[],
    )
    validation_ref = store.write_json(bundle.validation, validation)
    outcome = OutcomeRecord(
        schema_version="2.0",
        agent_run_id="run-invalid",
        status="invalid",
        started_at="2026-09-13T08:00:00Z",
        completed_at="2026-09-13T08:00:02Z",
        duration_ms=2_000,
        input_path=bundle.input,
        input_hash=HASH,
        raw_output_path=bundle.raw_output,
        raw_output_hash=HASH,
        validation_path=bundle.validation,
        validation_hash=validation_ref.sha256,
        canonical_path=None,
        canonical_hash=None,
        tokens_in=10,
        tokens_out=2,
        cost_usd=None,
        error="schema validation failed",
    )
    store.write_json(bundle.outcome, outcome)

    assert json.loads(store.resolve(bundle.validation).read_text()) == validation.model_dump(
        mode="json"
    )
    assert json.loads(store.resolve(bundle.outcome).read_text()) == outcome.model_dump(
        mode="json"
    )


def test_sqlite_and_trace_accept_exact_run_models(tmp_path: Path) -> None:
    bundle = ArtifactStore(tmp_path).run_bundle("inv-test", "run-invalid")
    run = AgentRun(
        schema_version="2.0",
        agent_run_id="run-invalid",
        investigation_id="inv-test",
        paper_id="paper-1",
        role="paper_reader",
        job_type="paper_read",
        attempt_no=1,
        status="invalid",
        model="model-test",
        agent_definition_hash=HASH,
        component_skill_hash=None,
        objective_profile_hash=HASH,
        input_path=bundle.input,
        input_hash=HASH,
        raw_output_path=bundle.raw_output,
        raw_output_hash=HASH,
        validation_path=bundle.validation,
        validation_hash=HASH,
        canonical_path=None,
        canonical_hash=None,
        started_at="2026-09-13T08:00:00Z",
        completed_at="2026-09-13T08:00:02Z",
        duration_ms=2_000,
        tokens_in=10,
        tokens_out=2,
        cost_usd=None,
        error="schema validation failed",
    )
    index = SQLiteIndex(tmp_path / "data/triage-v2.db")
    index.initialize()
    index.ingest_rows(base_rows())
    index.upsert_agent_run(run)
    projected = index.agent_run_rows()[0]
    assert projected["status"] == "invalid"
    assert projected["validation_hash"] == HASH

    started = TraceEvent(
        schema_version="2.0",
        event_id="evt-run-invalid-started",
        event_type="agent_run.started",
        timestamp="2026-09-13T08:00:00Z",
        agent_run_id="run-invalid",
        investigation_id="inv-test",
        paper_id="paper-1",
        role="paper_reader",
        job_type="paper_read",
        attempt_no=1,
        sequence=1,
        model="model-test",
        agent_definition_hash=HASH,
        component_skill_hash=None,
        objective_profile_hash=HASH,
        input_path=bundle.input,
        input_hash=HASH,
        artifact_path=None,
        artifact_hash=None,
        tokens_in=None,
        tokens_out=None,
        cost_usd=None,
        error=None,
    )
    trace_path = tmp_path / "logs/trace.jsonl"
    TraceAppender(trace_path).append(started)
    assert list(iter_trace(trace_path)) == [started.model_dump(mode="json")]
    index.close()


def test_canonical_promotion_copies_parsed_bytes_exactly(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    parsed = b'{\n  "input_hash": "' + HASH.encode() + b'", "value": "exact"\n}'
    store.write_bytes("data/investigations/inv/runs/run/parsed.json", parsed)
    promoted = store.promote_parsed(
        "data/investigations/inv/runs/run/parsed.json",
        "data/investigations/inv/papers/paper/reader/canonical.json",
        expected_input_hash=HASH,
    )
    assert store.resolve(promoted.path).read_bytes() == parsed


def test_trace_is_append_only_and_replay_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "logs/trace.jsonl"
    appender = TraceAppender(path)
    started = event("run-1", "agent_run.started", 1)
    appender.append(started)
    appender.append(started)
    assert len(list(iter_trace(path))) == 2
    assert list(replay_unique(path)) == [started]


def test_sqlite_foreign_keys_and_ingestion_transaction_rollback(tmp_path: Path) -> None:
    index = SQLiteIndex(tmp_path / "triage.db")
    index.initialize()
    broken = base_rows()
    broken["investigations"][0]["search_plan_hash"] = "b" * 64
    with pytest.raises(sqlite3.IntegrityError):
        index.ingest_rows(broken)
    assert index.connect().execute("SELECT COUNT(*) FROM objective_profiles").fetchone()[0] == 0
    index.close()


def test_legacy_overlapping_schema_fails_loudly(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE papers (arxiv_id TEXT PRIMARY KEY)")
    with pytest.raises(StorageSchemaError, match="migration policy is not defined"):
        SQLiteIndex(path).initialize()


def test_exact_row_replay_is_idempotent_but_conflict_is_not(tmp_path: Path) -> None:
    index = SQLiteIndex(tmp_path / "triage.db")
    index.initialize()
    rows = base_rows()
    index.ingest_rows(rows)
    index.ingest_rows(rows)
    conflict = {"papers": [dict(rows["papers"][0], title="Changed title")]}
    with pytest.raises(ProjectionConflictError):
        index.ingest_rows(conflict)
    index.close()


def test_rebuild_replaces_only_index_with_equivalent_projection(tmp_path: Path) -> None:
    path = tmp_path / "triage.db"
    rows = base_rows(include_run=True)
    rebuild_index(path, rows)
    with sqlite3.connect(path) as connection:
        first = list(connection.iterdump())
    rebuild_index(path, rows)
    with sqlite3.connect(path) as connection:
        second = list(connection.iterdump())
    assert first == second


def test_serialized_writer_accepts_concurrent_independent_runs(tmp_path: Path) -> None:
    index = SQLiteIndex(tmp_path / "triage.db")
    index.initialize()
    rows = base_rows()
    rows["papers"].extend(
        dict(rows["papers"][0], paper_id=f"paper-{number}", identity_path=f"data/papers/paper-{number}/identity.json")
        for number in range(2, 7)
    )
    index.ingest_rows(rows)

    def insert(number: int) -> None:
        row = agent_run_row(f"run-{number}")
        row["paper_id"] = f"paper-{number}"
        index.upsert_agent_run(row)

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(insert, range(1, 7)))
    assert len(index.agent_run_rows()) == 6
    index.close()


def test_sqlite_accepts_review_blocked_and_membership_unresolved(tmp_path: Path) -> None:
    index = SQLiteIndex(tmp_path / "triage-v2.db")
    index.initialize()
    rows = base_rows()
    rows["investigations"][0]["status"] = "review_blocked"
    rows["corpus_membership"] = [
        {
            "investigation_id": "inv-test",
            "paper_id": "paper-1",
            "ordinal": 1,
            "membership_status": "membership_unresolved",
            "terminal_state": None,
            "source_document_id": None,
            "inclusion_reason": None,
            "exclusion_reason": None,
            "state_path": None,
        }
    ]
    index.ingest_rows(rows)
    connection = index.connect()
    assert connection.execute(
        "SELECT status FROM investigations WHERE investigation_id = 'inv-test'"
    ).fetchone()[0] == "review_blocked"
    assert connection.execute(
        "SELECT membership_status FROM corpus_membership"
    ).fetchone()[0] == "membership_unresolved"
    index.close()


def test_sqlite_schema_matches_minimal_finalized_run_and_critic_contracts(
    tmp_path: Path,
) -> None:
    index = SQLiteIndex(tmp_path / "triage-v2.db")
    index.initialize()
    connection = index.connect()

    critic_columns = {
        row[1]: row for row in connection.execute("PRAGMA table_info(critic_records)")
    }
    assert "human_review_required" not in critic_columns

    assessment_columns = {
        row[1]: row
        for row in connection.execute("PRAGMA table_info(objective_assessments)")
    }
    assert "assessment_id" not in assessment_columns
    assert "label" not in assessment_columns
    assert assessment_columns["score"][3] == 1

    finding_columns = {
        row[1]: row for row in connection.execute("PRAGMA table_info(review_findings)")
    }
    assert "finding_type" not in finding_columns
    assert finding_columns["review_record_id"][5] == 1
    assert finding_columns["finding_id"][5] == 2

    review_evidence_columns = {
        row[1]: row for row in connection.execute("PRAGMA table_info(review_evidence)")
    }
    assert review_evidence_columns["paper_id"][3] == 1
    assert review_evidence_columns["review_record_id"][5] == 1
    assert review_evidence_columns["finding_id"][5] == 2
    assert review_evidence_columns["paper_id"][5] == 4
    assert review_evidence_columns["evidence_id"][5] == 5

    index.ingest_rows(base_rows())
    orchestrator = agent_run_row("run-orchestrator")
    orchestrator.update(role="orchestrator", paper_id=None)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        index.upsert_agent_run(orchestrator)
    index.close()


def test_claim_ids_are_local_to_reader_records_through_evidence_projection(
    tmp_path: Path,
) -> None:
    index = SQLiteIndex(tmp_path / "triage-v2.db")
    index.initialize()
    rows = base_rows()
    rows["papers"].append(
        dict(
            rows["papers"][0],
            paper_id="paper-2",
            identity_path="data/papers/paper-2/identity.json",
        )
    )
    rows["source_documents"] = [
        {
            "source_document_id": f"source-{number}",
            "paper_id": f"paper-{number}",
            "status": "frozen",
            "format": "html",
            "retrieval_method": "direct",
            "source_url": None,
            "packet_path": f"data/papers/paper-{number}/source.json",
            "packet_hash": HASH,
            "original_path": None,
            "original_sha256": None,
            "normalized_path": None,
            "normalized_sha256": None,
            "retrieved_at": "2026-09-13T08:00:00Z",
            "error": None,
        }
        for number in (1, 2)
    ]
    reader_runs = [agent_run_row(f"run-reader-{number}") for number in (1, 2)]
    reader_runs[1]["paper_id"] = "paper-2"
    critic_runs = [agent_run_row(f"run-critic-{number}") for number in (1, 2)]
    for number, run in enumerate(critic_runs, start=1):
        run.update(
            paper_id=f"paper-{number}",
            role="critic",
            job_type="paper_critique",
        )
    rows["agent_runs"] = reader_runs + critic_runs
    rows["reader_records"] = [
        {
            "reader_record_id": f"reader-{number}",
            "agent_run_id": f"run-reader-{number}",
            "investigation_id": "inv-test",
            "paper_id": f"paper-{number}",
            "source_document_id": f"source-{number}",
            "input_hash": HASH,
            "artifact_path": f"data/readers/reader-{number}.json",
            "artifact_hash": HASH,
        }
        for number in (1, 2)
    ]
    rows["claims"] = [
        {
            "reader_record_id": f"reader-{number}",
            "claim_id": "claim-local",
            "claim_index": 0,
            "claim_kind": "result",
            "text": f"Result from paper {number}",
            "document_sha256": HASH,
            "section_id": "section-1",
            "start_char": 0,
            "end_char": 6,
            "source_quote": "Result",
            "evidence_modality": "experiment",
            "execution_environment": "real_hardware",
            "provenance": "paper_stated",
        }
        for number in (1, 2)
    ]
    rows["critic_records"] = [
        {
            "critic_record_id": f"critic-{number}",
            "agent_run_id": f"run-critic-{number}",
            "investigation_id": "inv-test",
            "paper_id": f"paper-{number}",
            "reader_record_id": f"reader-{number}",
            "input_hash": HASH,
            "artifact_path": f"data/critics/critic-{number}.json",
            "artifact_hash": HASH,
        }
        for number in (1, 2)
    ]
    rows["verdicts"] = [
        {
            "critic_record_id": f"critic-{number}",
            "reader_record_id": f"reader-{number}",
            "claim_id": "claim-local",
            "status": "supported",
            "evidence_classification_correct": True,
            "reason": "Bounded support",
        }
        for number in (1, 2)
    ]
    rows["objective_assessments"] = [
        {
            "critic_record_id": f"critic-{number}",
            "criterion_id": "criterion-1",
            "score": 3,
            "reason": "Bounded assessment",
            "assumptions_json": [],
            "uncertain": False,
        }
        for number in (1, 2)
    ]
    rows["assessment_evidence"] = [
        {
            "critic_record_id": f"critic-{number}",
            "criterion_id": "criterion-1",
            "reader_record_id": f"reader-{number}",
            "claim_id": "claim-local",
        }
        for number in (1, 2)
    ]

    index.ingest_rows(rows)
    connection = index.connect()
    assert connection.execute(
        "SELECT COUNT(*) FROM claims WHERE claim_id = 'claim-local'"
    ).fetchone()[0] == 2
    assert connection.execute(
        "SELECT COUNT(*) FROM verdicts WHERE claim_id = 'claim-local'"
    ).fetchone()[0] == 2
    assert connection.execute(
        "SELECT COUNT(*) FROM assessment_evidence WHERE claim_id = 'claim-local'"
    ).fetchone()[0] == 2
    index.close()


def test_sqlite_does_not_rewrite_a_terminal_invalid_attempt(tmp_path: Path) -> None:
    index = SQLiteIndex(tmp_path / "triage-v2.db")
    index.initialize()
    index.ingest_rows(base_rows())
    invalid = agent_run_row("run-invalid")
    invalid["status"] = "invalid"
    index.upsert_agent_run(invalid)

    with pytest.raises(ProjectionConflictError, match="terminal status cannot change"):
        index.upsert_agent_run(dict(invalid, status="failed"))
    with pytest.raises(ProjectionConflictError, match="terminal projection cannot change"):
        index.upsert_agent_run(dict(invalid, error="rewritten after validation"))

    assert index.agent_run_rows()[0]["status"] == "invalid"
    assert index.agent_run_rows()[0]["error"] is None
    index.close()


def test_sqlite_terminal_agent_run_replay_is_idempotent(tmp_path: Path) -> None:
    index = SQLiteIndex(tmp_path / "triage-v2.db")
    index.initialize()
    index.ingest_rows(base_rows())
    invalid = agent_run_row("run-invalid")
    invalid.update(status="invalid", error="schema validation failed")
    index.upsert_agent_run(invalid)
    index.upsert_agent_run(invalid)
    assert index.agent_run_rows()[0]["error"] == "schema validation failed"
    index.close()


def test_reconcile_detects_interruption_and_repairs_promoted_trace(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    trace_path = tmp_path / "logs/trace.jsonl"
    appender = TraceAppender(trace_path)

    interrupted = "run-interrupted"
    bundle = store.run_bundle("inv-test", interrupted)
    store.write_json(bundle.input, {"input_hash": HASH})
    store.write_text(bundle.raw_output, '{"partial":"response arrived"}')
    appender.append(event(interrupted, "agent_run.started", 1))

    promoted = "run-promoted"
    promoted_bundle = store.run_bundle("inv-test", promoted)
    store.write_json(promoted_bundle.input, {"input_hash": HASH})
    canonical_path = "data/investigations/inv-test/papers/paper-1/reader/canonical.json"
    canonical = store.write_json(canonical_path, {"input_hash": HASH})
    store.write_json(
        promoted_bundle.outcome,
        {
            "status": "completed",
            "validation_pass": True,
            "canonical_path": canonical_path,
            "canonical_hash": canonical.sha256,
        },
    )
    appender.append(event(promoted, "agent_run.started", 1))

    index = SQLiteIndex(tmp_path / "data/triage.db")
    index.initialize()
    report = Reconciler(tmp_path, index=index).inspect("inv-test")
    assert [item.agent_run_id for item in report.interrupted] == [interrupted]
    assert [item.agent_run_id for item in report.append_reconciled] == [promoted]

    Reconciler(tmp_path, index=index).apply_safe_repairs(report)
    assert "agent_run.reconciled" in {
        item["event_type"] for item in iter_trace(trace_path) if item["agent_run_id"] == promoted
    }
    index.close()


def test_reconcile_reports_missing_index_and_unsupported_index_rows(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    appender = TraceAppender(tmp_path / "logs/trace.jsonl")

    completed = "run-completed"
    completed_bundle = store.run_bundle("inv-test", completed)
    store.write_json(completed_bundle.input, {"input_hash": HASH})
    canonical_path = "data/investigations/inv-test/papers/paper-1/critic/canonical.json"
    canonical = store.write_json(canonical_path, {"input_hash": HASH})
    store.write_json(
        completed_bundle.outcome,
        {
            "status": "completed",
            "validation_pass": True,
            "canonical_path": canonical_path,
            "canonical_hash": canonical.sha256,
        },
    )
    appender.append(event(completed, "agent_run.started", 1))
    completed_event = event(completed, "agent_run.completed", 2)
    completed_event["artifact_path"] = canonical_path
    completed_event["artifact_hash"] = canonical.sha256
    appender.append(completed_event)

    index = SQLiteIndex(tmp_path / "data/triage.db")
    index.initialize()
    rows = base_rows()
    unsupported = agent_run_row("run-db-only")
    unsupported["status"] = "completed"
    unsupported["canonical_path"] = (
        "data/investigations/inv-test/papers/paper-1/reader/missing.json"
    )
    unsupported["canonical_hash"] = HASH
    rows["agent_runs"] = [unsupported]
    index.ingest_rows(rows)

    report = Reconciler(tmp_path, index=index).inspect("inv-test")
    assert [item.agent_run_id for item in report.reindex_required] == [completed]
    assert [item.agent_run_id for item in report.integrity_errors] == ["run-db-only"]
    assert "no supporting trace" in report.integrity_errors[0].detail
    assert "artifact is missing" in report.integrity_errors[0].detail
    index.close()


@pytest.mark.parametrize(
    ("event_type", "status"),
    [
        ("agent_run.invalid", "invalid"),
        ("agent_run.failed", "failed"),
    ],
)
def test_reconcile_preserves_terminal_noncompletion_attempts(
    tmp_path: Path, event_type: str, status: str
) -> None:
    store = ArtifactStore(tmp_path)
    appender = TraceAppender(tmp_path / "logs/trace.jsonl")
    run_id = f"run-{status}"
    bundle = store.run_bundle("inv-test", run_id)
    store.write_json(bundle.input, {"input_hash": HASH})
    store.write_json(bundle.outcome, {"status": status, "error": "visible failure"})
    appender.append(event(run_id, "agent_run.started", 1))
    terminal = event(run_id, event_type, 2)
    terminal["error"] = "visible failure"
    appender.append(terminal)

    index = SQLiteIndex(tmp_path / "data/triage-v2.db")
    index.initialize()
    index.ingest_rows(base_rows())
    row = agent_run_row(run_id)
    row.update(status=status, error="visible failure")
    index.upsert_agent_run(row)

    report = Reconciler(tmp_path, index=index).inspect("inv-test")
    assert report.interrupted == ()
    assert report.reindex_required == ()
    assert report.integrity_errors == ()
    index.close()


def test_reconcile_flags_terminal_trace_without_outcome_instead_of_retrying(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path)
    appender = TraceAppender(tmp_path / "logs/trace.jsonl")
    run_id = "run-invalid"
    bundle = store.run_bundle("inv-test", run_id)
    store.write_json(bundle.input, {"input_hash": HASH})
    appender.append(event(run_id, "agent_run.started", 1))
    terminal = event(run_id, "agent_run.invalid", 2)
    terminal["error"] = "schema validation failed"
    appender.append(terminal)

    report = Reconciler(tmp_path).inspect("inv-test")
    assert report.interrupted == ()
    assert report.reindex_required == ()
    assert [item.agent_run_id for item in report.integrity_errors] == [run_id]
    assert "no outcome.json" in report.integrity_errors[0].detail
