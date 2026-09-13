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
