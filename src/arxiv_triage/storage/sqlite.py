"""Rebuildable SQLite projection for schema 2.0 artifacts.

The index accepts already-validated, already-projected rows.  It intentionally
does not infer research semantics from JSON artifacts; that mapping belongs to
the validation/projection boundary which can use the schema models.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from collections.abc import Iterable, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class StorageSchemaError(RuntimeError):
    """Raised when a database does not match the schema 2.0 projection."""


class ProjectionConflictError(RuntimeError):
    """Raised when an immutable projected row exists with different values."""


TABLE_ORDER = (
    "objective_profiles",
    "search_plans",
    "investigations",
    "papers",
    "paper_identifiers",
    "source_documents",
    "corpus_membership",
    "agent_runs",
    "reader_records",
    "claims",
    "critic_records",
    "verdicts",
    "objective_assessments",
    "assessment_evidence",
    "review_records",
    "review_findings",
    "review_evidence",
)


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS objective_profiles (
    profile_hash TEXT PRIMARY KEY, profile_id TEXT NOT NULL,
    schema_version TEXT NOT NULL, component TEXT NOT NULL, origin TEXT NOT NULL,
    artifact_path TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS search_plans (
    search_plan_hash TEXT PRIMARY KEY, search_plan_id TEXT NOT NULL,
    schema_version TEXT NOT NULL, component TEXT NOT NULL,
    artifact_path TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS investigations (
    investigation_id TEXT PRIMARY KEY, schema_version TEXT NOT NULL,
    kind TEXT NOT NULL, question TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'draft','inputs_validated','discovering','corpus_frozen','analyzing',
        'reviewing','rendering','complete','complete_with_warnings','failed')),
    spec_path TEXT NOT NULL UNIQUE, spec_hash TEXT NOT NULL,
    profile_hash TEXT NOT NULL REFERENCES objective_profiles(profile_hash),
    search_plan_hash TEXT NOT NULL REFERENCES search_plans(search_plan_hash),
    corpus_path TEXT, corpus_hash TEXT, created_at TEXT NOT NULL, completed_at TEXT
);
CREATE TABLE IF NOT EXISTS papers (
    paper_id TEXT PRIMARY KEY, schema_version TEXT NOT NULL, title TEXT NOT NULL,
    authors_json TEXT NOT NULL, published TEXT,
    identity_status TEXT NOT NULL CHECK (identity_status IN (
        'unresolved','resolved_exact','resolved_probable','ambiguous')),
    identity_path TEXT NOT NULL UNIQUE, identity_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS paper_identifiers (
    paper_id TEXT NOT NULL REFERENCES papers(paper_id),
    scheme TEXT NOT NULL CHECK (scheme IN ('arxiv','doi','openreview','url','proceedings')),
    value TEXT NOT NULL, url TEXT, PRIMARY KEY (paper_id, scheme, value),
    UNIQUE (scheme, value)
);
CREATE TABLE IF NOT EXISTS source_documents (
    source_document_id TEXT PRIMARY KEY,
    paper_id TEXT NOT NULL REFERENCES papers(paper_id),
    status TEXT NOT NULL CHECK (status IN ('frozen','failed')),
    format TEXT NOT NULL, retrieval_method TEXT NOT NULL, source_url TEXT,
    packet_path TEXT NOT NULL UNIQUE, packet_hash TEXT NOT NULL,
    original_path TEXT, original_sha256 TEXT, normalized_path TEXT,
    normalized_sha256 TEXT, retrieved_at TEXT NOT NULL, error TEXT,
    UNIQUE (paper_id, packet_hash)
);
CREATE TABLE IF NOT EXISTS corpus_membership (
    investigation_id TEXT NOT NULL REFERENCES investigations(investigation_id),
    paper_id TEXT NOT NULL REFERENCES papers(paper_id), ordinal INTEGER NOT NULL,
    membership_status TEXT NOT NULL CHECK (membership_status IN ('included','excluded','unresolved')),
    terminal_state TEXT CHECK (terminal_state IN ('complete','unresolved','failed')),
    source_document_id TEXT REFERENCES source_documents(source_document_id),
    inclusion_reason TEXT, exclusion_reason TEXT, state_path TEXT,
    PRIMARY KEY (investigation_id, paper_id), UNIQUE (investigation_id, ordinal)
);
CREATE TABLE IF NOT EXISTS agent_runs (
    agent_run_id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL REFERENCES investigations(investigation_id),
    paper_id TEXT REFERENCES papers(paper_id),
    role TEXT NOT NULL CHECK (role IN ('orchestrator','paper_reader','critic','reviewer')),
    job_type TEXT NOT NULL, attempt_no INTEGER NOT NULL CHECK (attempt_no BETWEEN 1 AND 2),
    status TEXT NOT NULL CHECK (status IN (
        'running','output_received','invalid','completed','failed','interrupted')),
    model TEXT NOT NULL, agent_definition_hash TEXT NOT NULL,
    component_skill_hash TEXT,
    objective_profile_hash TEXT REFERENCES objective_profiles(profile_hash),
    input_path TEXT NOT NULL, input_hash TEXT NOT NULL,
    raw_output_path TEXT, raw_output_hash TEXT, validation_path TEXT,
    canonical_path TEXT, canonical_hash TEXT, started_at TEXT NOT NULL,
    completed_at TEXT, duration_ms INTEGER, tokens_in INTEGER, tokens_out INTEGER,
    cost_usd REAL, error TEXT,
    UNIQUE (investigation_id, paper_id, job_type, attempt_no)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_corpus_job_attempt
ON agent_runs(investigation_id, job_type, attempt_no) WHERE paper_id IS NULL;
CREATE TABLE IF NOT EXISTS reader_records (
    reader_record_id TEXT PRIMARY KEY,
    agent_run_id TEXT NOT NULL UNIQUE REFERENCES agent_runs(agent_run_id),
    investigation_id TEXT NOT NULL REFERENCES investigations(investigation_id),
    paper_id TEXT NOT NULL REFERENCES papers(paper_id),
    source_document_id TEXT NOT NULL REFERENCES source_documents(source_document_id),
    input_hash TEXT NOT NULL, artifact_path TEXT NOT NULL UNIQUE,
    artifact_hash TEXT NOT NULL, UNIQUE (investigation_id, paper_id)
);
CREATE TABLE IF NOT EXISTS claims (
    claim_id TEXT PRIMARY KEY,
    reader_record_id TEXT NOT NULL REFERENCES reader_records(reader_record_id),
    claim_index INTEGER NOT NULL, claim_kind TEXT NOT NULL, text TEXT NOT NULL,
    document_sha256 TEXT, section_id TEXT, start_char INTEGER, end_char INTEGER,
    source_quote TEXT, evidence_modality TEXT NOT NULL,
    execution_environment TEXT NOT NULL, provenance TEXT NOT NULL,
    UNIQUE (reader_record_id, claim_index)
);
CREATE TABLE IF NOT EXISTS critic_records (
    critic_record_id TEXT PRIMARY KEY,
    agent_run_id TEXT NOT NULL UNIQUE REFERENCES agent_runs(agent_run_id),
    investigation_id TEXT NOT NULL REFERENCES investigations(investigation_id),
    paper_id TEXT NOT NULL REFERENCES papers(paper_id),
    reader_record_id TEXT NOT NULL UNIQUE REFERENCES reader_records(reader_record_id),
    input_hash TEXT NOT NULL, artifact_path TEXT NOT NULL UNIQUE,
    artifact_hash TEXT NOT NULL,
    human_review_required INTEGER NOT NULL CHECK (human_review_required IN (0,1)),
    UNIQUE (investigation_id, paper_id)
);
CREATE TABLE IF NOT EXISTS verdicts (
    critic_record_id TEXT NOT NULL REFERENCES critic_records(critic_record_id),
    claim_id TEXT NOT NULL REFERENCES claims(claim_id),
    status TEXT NOT NULL CHECK (status IN ('supported','unsupported','overclaimed')),
    evidence_classification_correct INTEGER NOT NULL CHECK (evidence_classification_correct IN (0,1)),
    reason TEXT NOT NULL, PRIMARY KEY (critic_record_id, claim_id)
);
CREATE TABLE IF NOT EXISTS objective_assessments (
    assessment_id TEXT PRIMARY KEY,
    critic_record_id TEXT NOT NULL REFERENCES critic_records(critic_record_id),
    criterion_id TEXT NOT NULL, score INTEGER CHECK (score BETWEEN 0 AND 5),
    label TEXT, reason TEXT NOT NULL, assumptions_json TEXT NOT NULL,
    uncertain INTEGER NOT NULL CHECK (uncertain IN (0,1)),
    UNIQUE (critic_record_id, criterion_id)
);
CREATE TABLE IF NOT EXISTS assessment_evidence (
    assessment_id TEXT NOT NULL REFERENCES objective_assessments(assessment_id),
    claim_id TEXT NOT NULL REFERENCES claims(claim_id),
    PRIMARY KEY (assessment_id, claim_id)
);
CREATE TABLE IF NOT EXISTS review_records (
    review_record_id TEXT PRIMARY KEY,
    agent_run_id TEXT NOT NULL UNIQUE REFERENCES agent_runs(agent_run_id),
    investigation_id TEXT NOT NULL UNIQUE REFERENCES investigations(investigation_id),
    input_hash TEXT NOT NULL,
    report_status TEXT NOT NULL CHECK (report_status IN ('ready','ready_with_warnings','blocked')),
    artifact_path TEXT NOT NULL UNIQUE, artifact_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS review_findings (
    finding_id TEXT PRIMARY KEY,
    review_record_id TEXT NOT NULL REFERENCES review_records(review_record_id),
    finding_type TEXT NOT NULL, text TEXT NOT NULL, provenance TEXT NOT NULL,
    uncertain INTEGER NOT NULL CHECK (uncertain IN (0,1))
);
CREATE TABLE IF NOT EXISTS review_evidence (
    finding_id TEXT NOT NULL REFERENCES review_findings(finding_id),
    evidence_type TEXT NOT NULL CHECK (evidence_type IN ('claim','verdict','assessment','corpus_entry')),
    evidence_id TEXT NOT NULL,
    PRIMARY KEY (finding_id, evidence_type, evidence_id)
);
CREATE INDEX IF NOT EXISTS idx_corpus_terminal
ON corpus_membership(investigation_id, terminal_state);
CREATE INDEX IF NOT EXISTS idx_runs_scope
ON agent_runs(investigation_id, paper_id, job_type, status);
CREATE INDEX IF NOT EXISTS idx_claims_reader ON claims(reader_record_id);
CREATE INDEX IF NOT EXISTS idx_assessments_criterion ON objective_assessments(criterion_id);
"""


EXPECTED_SENTINELS: dict[str, frozenset[str]] = {
    "papers": frozenset({"paper_id", "schema_version", "identity_path", "identity_hash"}),
    "claims": frozenset({"claim_id", "reader_record_id", "source_quote"}),
    "agent_runs": frozenset({"agent_run_id", "input_path", "canonical_hash"}),
}


class SQLiteIndex:
    """A serialized writer for the rebuildable query index."""

    def __init__(self, path: Path | str, *, busy_timeout_ms: int = 5000) -> None:
        self.path = Path(path)
        self.busy_timeout_ms = busy_timeout_ms
        self._lock = threading.RLock()
        self._connection: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        if self._connection is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.path, check_same_thread=False)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(f"PRAGMA busy_timeout = {int(self.busy_timeout_ms)}")
            connection.execute("PRAGMA journal_mode = WAL")
            self._connection = connection
        return self._connection

    def initialize(self) -> None:
        with self._lock:
            connection = self.connect()
            self._reject_incompatible_existing_schema(connection)
            connection.executescript(SCHEMA_SQL)
            connection.commit()

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    def __enter__(self) -> "SQLiteIndex":
        self.initialize()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Serialize one ingestion unit and roll it back on any failure."""

        with self._lock:
            connection = self.connect()
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()

    def ingest_rows(self, rows_by_table: Mapping[str, Iterable[Mapping[str, Any]]]) -> None:
        """Insert a dependency-ordered artifact projection in one transaction.

        Replaying an identical row is idempotent.  A primary/unique-key clash
        with different projected bytes raises instead of silently replacing
        evidence.
        """

        unknown = set(rows_by_table).difference(TABLE_ORDER)
        if unknown:
            raise StorageSchemaError(f"unknown projection tables: {sorted(unknown)}")
        with self.transaction() as connection:
            for table in TABLE_ORDER:
                for row in rows_by_table.get(table, ()):
                    self._insert_exact(connection, table, row)

    def upsert_agent_run(self, row: Mapping[str, Any]) -> None:
        """Insert a run or advance only its mutable lifecycle projection."""

        required_identity = {
            "agent_run_id",
            "investigation_id",
            "paper_id",
            "role",
            "job_type",
            "attempt_no",
            "model",
            "agent_definition_hash",
            "component_skill_hash",
            "objective_profile_hash",
            "input_path",
            "input_hash",
            "started_at",
        }
        missing = required_identity.difference(row)
        if missing:
            raise StorageSchemaError(f"agent run row is missing fields: {sorted(missing)}")
        with self.transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM agent_runs WHERE agent_run_id = ?", (row["agent_run_id"],)
            ).fetchone()
            if existing is None:
                self._execute_insert(connection, "agent_runs", row)
                return
            for field in required_identity:
                if existing[field] != row[field]:
                    raise ProjectionConflictError(
                        f"agent run immutable field changed: {field}"
                    )
            mutable = [
                field
                for field in row
                if field not in required_identity and field != "agent_run_id"
            ]
            self._validate_columns(connection, "agent_runs", row)
            if mutable:
                assignments = ", ".join(f'"{field}" = ?' for field in mutable)
                values = [self._sql_value(row[field]) for field in mutable]
                values.append(row["agent_run_id"])
                connection.execute(
                    f'UPDATE "agent_runs" SET {assignments} WHERE agent_run_id = ?', values
                )

    def has_agent_run(self, agent_run_id: str) -> bool:
        with self._lock:
            row = self.connect().execute(
                "SELECT 1 FROM agent_runs WHERE agent_run_id = ?", (agent_run_id,)
            ).fetchone()
            return row is not None

    def agent_run_rows(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.connect().execute("SELECT * FROM agent_runs ORDER BY agent_run_id")
            return [dict(row) for row in rows]

    def integrity_check(self) -> list[str]:
        with self._lock:
            connection = self.connect()
            errors = [row[0] for row in connection.execute("PRAGMA integrity_check") if row[0] != "ok"]
            errors.extend(
                f"foreign key violation: {tuple(row)}"
                for row in connection.execute("PRAGMA foreign_key_check")
            )
            return errors

    def mark_interrupted(self, agent_run_id: str) -> bool:
        """Mark a persisted nonterminal attempt interrupted during recovery."""

        with self.transaction() as connection:
            cursor = connection.execute(
                "UPDATE agent_runs SET status = 'interrupted' "
                "WHERE agent_run_id = ? AND status IN ('running', 'output_received')",
                (agent_run_id,),
            )
            return cursor.rowcount == 1

    @staticmethod
    def _reject_incompatible_existing_schema(connection: sqlite3.Connection) -> None:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        for table, sentinel_columns in EXPECTED_SENTINELS.items():
            if table not in tables:
                continue
            actual = {
                row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')
            }
            if not sentinel_columns.issubset(actual):
                raise StorageSchemaError(
                    f"existing table {table!r} is incompatible with schema 2.0; "
                    "migration policy is not defined"
                )

    @staticmethod
    def _validate_columns(
        connection: sqlite3.Connection, table: str, row: Mapping[str, Any]
    ) -> None:
        if table not in TABLE_ORDER:
            raise StorageSchemaError(f"unknown projection table: {table}")
        columns = {
            result[1] for result in connection.execute(f'PRAGMA table_info("{table}")')
        }
        unknown = set(row).difference(columns)
        if unknown:
            raise StorageSchemaError(f"unknown columns for {table}: {sorted(unknown)}")
        if not row:
            raise StorageSchemaError(f"cannot insert an empty row into {table}")

    @classmethod
    def _execute_insert(
        cls, connection: sqlite3.Connection, table: str, row: Mapping[str, Any]
    ) -> None:
        cls._validate_columns(connection, table, row)
        columns = list(row)
        names = ", ".join(f'"{column}"' for column in columns)
        placeholders = ", ".join("?" for _ in columns)
        connection.execute(
            f'INSERT INTO "{table}" ({names}) VALUES ({placeholders})',
            [cls._sql_value(row[column]) for column in columns],
        )

    @classmethod
    def _insert_exact(
        cls, connection: sqlite3.Connection, table: str, row: Mapping[str, Any]
    ) -> None:
        try:
            cls._execute_insert(connection, table, row)
        except sqlite3.IntegrityError as exc:
            conflict_codes = {
                getattr(sqlite3, "SQLITE_CONSTRAINT_PRIMARYKEY", 1555),
                getattr(sqlite3, "SQLITE_CONSTRAINT_UNIQUE", 2067),
            }
            if getattr(exc, "sqlite_errorcode", None) not in conflict_codes:
                raise
            cls._validate_columns(connection, table, row)
            columns = list(row)
            predicates = " AND ".join(f'"{column}" IS ?' for column in columns)
            values = [cls._sql_value(row[column]) for column in columns]
            identical = connection.execute(
                f'SELECT 1 FROM "{table}" WHERE {predicates} LIMIT 1', values
            ).fetchone()
            if identical is None:
                raise ProjectionConflictError(
                    f"non-identical row conflicts in {table}"
                ) from exc

    @staticmethod
    def _sql_value(value: Any) -> Any:
        if isinstance(value, (dict, list)):
            return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if isinstance(value, bool):
            return int(value)
        return value


def rebuild_index(
    path: Path | str,
    rows_by_table: Mapping[str, Iterable[Mapping[str, Any]]],
    *,
    busy_timeout_ms: int = 5000,
) -> None:
    """Build a complete index beside the target and atomically replace it.

    Callers obtain ``rows_by_table`` by validating authoritative artifacts.
    No artifact is edited or removed.  If projection fails, the prior index is
    left untouched.
    """

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.rebuild-{uuid.uuid4().hex}.tmp")
    index = SQLiteIndex(temporary, busy_timeout_ms=busy_timeout_ms)
    try:
        index.initialize()
        index.ingest_rows(rows_by_table)
        connection = index.connect()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        errors = index.integrity_check()
        if errors:
            raise StorageSchemaError("rebuilt index failed integrity check: " + "; ".join(errors))
        index.close()
        os.replace(temporary, target)
        directory_fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        index.close()
        temporary.unlink(missing_ok=True)
        temporary.with_name(temporary.name + "-wal").unlink(missing_ok=True)
        temporary.with_name(temporary.name + "-shm").unlink(missing_ok=True)
