#!/usr/bin/env python3
"""SQLite store for arxiv-triage: the trace, the claims, and the judgments.

Two commands:

    uv run scripts/db.py init
    uv run scripts/db.py ingest <artifact-path> --model <model-id>

Design rules (see docs/decisions.md):
  * Runs are append-only. A re-read is a new run, never an update.
  * A path locates an artifact; a sha256 proves it. Both are stored.
  * Agents write files. Only this script writes to the database.

Standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB = Path("data/triage.db")

# role -> the agent definition whose hash identifies the version
AGENT_FILES = {
    "reader": Path(".claude/agents/paper-reader.md"),
    "critic": Path(".claude/agents/critic.md"),
}

EVIDENCE_TYPES = {"simulation", "real_hardware", "theory", "none_stated"}
PROVENANCE = {"peer_reviewed", "preprint", "blog_or_docs", "inferred"}
VERDICT_STATUS = {"supported", "unsupported", "overclaimed"}

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS papers (
    arxiv_id    TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    abstract    TEXT NOT NULL DEFAULT '',
    published   TEXT,
    fetched_at  TEXT NOT NULL,
    input_hash  TEXT NOT NULL
);

-- One row per agent invocation. This table IS the trace.
CREATE TABLE IF NOT EXISTS runs (
    run_id           TEXT PRIMARY KEY,
    arxiv_id         TEXT NOT NULL REFERENCES papers(arxiv_id),
    role             TEXT NOT NULL CHECK (role IN ('reader', 'critic')),
    version          TEXT NOT NULL,
    model            TEXT,
    started_at       TEXT NOT NULL,
    ingested_at      TEXT NOT NULL,
    duration_ms      INTEGER,
    retry_count      INTEGER NOT NULL DEFAULT 0,
    validation_pass  INTEGER NOT NULL DEFAULT 1,
    error            TEXT,
    tokens_in        INTEGER,
    tokens_out       INTEGER,
    artifact_path    TEXT NOT NULL,
    artifact_sha256  TEXT NOT NULL,
    UNIQUE (role, artifact_sha256)
);

CREATE TABLE IF NOT EXISTS claims (
    claim_id       TEXT PRIMARY KEY,
    run_id         TEXT NOT NULL REFERENCES runs(run_id),
    arxiv_id       TEXT NOT NULL REFERENCES papers(arxiv_id),
    claim_index    INTEGER NOT NULL,
    text           TEXT NOT NULL,
    source_span    TEXT,
    evidence_type  TEXT NOT NULL,
    provenance     TEXT NOT NULL,
    UNIQUE (run_id, claim_index)
);

-- The reader's headline judgment: one row per reader run.
CREATE TABLE IF NOT EXISTS scores (
    run_id      TEXT PRIMARY KEY REFERENCES runs(run_id),
    arxiv_id    TEXT NOT NULL REFERENCES papers(arxiv_id),
    relevance   INTEGER NOT NULL CHECK (relevance BETWEEN 0 AND 5),
    importance  INTEGER NOT NULL CHECK (importance BETWEEN 0 AND 5),
    reason      TEXT NOT NULL,
    extendable  INTEGER NOT NULL CHECK (extendable IN (0, 1))
);

-- The critic's verdicts: one row per claim per critic run.
CREATE TABLE IF NOT EXISTS verdicts (
    run_id    TEXT NOT NULL REFERENCES runs(run_id),
    claim_id  TEXT NOT NULL REFERENCES claims(claim_id),
    status    TEXT NOT NULL CHECK (status IN ('supported', 'unsupported', 'overclaimed')),
    reason    TEXT,
    PRIMARY KEY (run_id, claim_id)
);

-- Hand labels for the golden set. The score script joins scores to this.
CREATE TABLE IF NOT EXISTS labels (
    arxiv_id    TEXT PRIMARY KEY REFERENCES papers(arxiv_id),
    relevance   INTEGER NOT NULL CHECK (relevance BETWEEN 0 AND 5),
    importance  INTEGER NOT NULL CHECK (importance BETWEEN 0 AND 5),
    note        TEXT,
    labeled_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runs_paper   ON runs(arxiv_id, role);
CREATE INDEX IF NOT EXISTS idx_runs_version ON runs(version);
CREATE INDEX IF NOT EXISTS idx_claims_paper ON claims(arxiv_id);
"""


# --------------------------------------------------------------------------- helpers

def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def die(message: str) -> "NoReturn":  # type: ignore[valid-type]
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


# --------------------------------------------------------------------- artifact parsing

FENCE = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)


def parse_artifact(path: Path) -> dict:
    """Read the structured record from a .json file or the first ```json fence in a .md."""
    if not path.is_file():
        die(f"artifact not found: {path}")
    raw = path.read_text(encoding="utf-8")

    if path.suffix == ".json":
        payload = raw
    else:
        match = FENCE.search(raw)
        if not match:
            die(f"no ```json block found in {path}; agents must emit one fenced JSON record")
        payload = match.group(1)

    try:
        record = json.loads(payload)
    except json.JSONDecodeError as exc:
        die(f"{path}: JSON record is malformed: {exc}")
    if not isinstance(record, dict):
        die(f"{path}: JSON record must be an object")
    return record


def version_for(role: str, model: str, agent_file: Path | None) -> str:
    """A version is the agent definition hash plus the model. Change either, change the version."""
    path = agent_file or AGENT_FILES.get(role)
    if path and path.is_file():
        stem = f"{path.stem}@{sha256_file(path)[:12]}"
    else:
        print(
            f"warning: agent definition {path} not found; recording version as 'nofile'",
            file=sys.stderr,
        )
        stem = "nofile"
    return f"{stem}+{model}"


def require(record: dict, field: str, path: Path):
    if field not in record or record[field] in (None, ""):
        die(f"{path}: record is missing required field '{field}'")
    return record[field]


# ------------------------------------------------------------------------------ init

def cmd_init(args) -> int:
    conn = connect(args.db)
    with conn:
        conn.executescript(SCHEMA)
    tables = [
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
    ]
    conn.close()
    print(f"initialized {args.db}")
    print("tables: " + ", ".join(tables))
    return 0


# ---------------------------------------------------------------------------- ingest

def ensure_paper(conn: sqlite3.Connection, record: dict, arxiv_id: str, allow_new: bool):
    row = conn.execute(
        "SELECT arxiv_id FROM papers WHERE arxiv_id = ?", (arxiv_id,)
    ).fetchone()
    if row:
        return
    if not allow_new:
        die(
            f"paper {arxiv_id} is not in the database. "
            "Run scripts/fetch.py first, or pass --allow-new-paper to insert a stub."
        )
    title = record.get("title") or f"(stub) {arxiv_id}"
    abstract = record.get("abstract", "")
    conn.execute(
        "INSERT INTO papers (arxiv_id, title, abstract, published, fetched_at, input_hash)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (
            arxiv_id,
            title,
            abstract,
            record.get("published"),
            now(),
            sha256_text(title + abstract),
        ),
    )
    print(f"note: inserted stub paper row for {arxiv_id}", file=sys.stderr)


def insert_run(conn, run_id, record, arxiv_id, role, version, model, artifact, digest) -> None:
    conn.execute(
        "INSERT INTO runs (run_id, arxiv_id, role, version, model, started_at, ingested_at,"
        " duration_ms, retry_count, validation_pass, error, tokens_in, tokens_out,"
        " artifact_path, artifact_sha256)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            run_id,
            arxiv_id,
            role,
            version,
            model,
            record.get("started_at") or now(),
            now(),
            record.get("duration_ms"),
            int(record.get("retry_count", 0)),
            1,
            record.get("error"),
            record.get("tokens_in"),
            record.get("tokens_out"),
            str(artifact),
            digest,
        ),
    )


def ingest_reader(conn, run_id, record, arxiv_id, path) -> dict:
    score = record.get("score") or record
    relevance = int(require(score, "relevance", path))
    importance = int(require(score, "importance", path))
    reason = require(score, "reason", path)
    extendable = 1 if score.get("extendable") else 0

    conn.execute(
        "INSERT INTO scores (run_id, arxiv_id, relevance, importance, reason, extendable)"
        " VALUES (?,?,?,?,?,?)",
        (run_id, arxiv_id, relevance, importance, reason, extendable),
    )

    claims = record.get("claims") or []
    if not isinstance(claims, list):
        die(f"{path}: 'claims' must be a list")

    written = []
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            die(f"{path}: claim {index} must be an object")
        text = require(claim, "text", path)
        evidence = claim.get("evidence_type", "none_stated")
        provenance = claim.get("provenance", "preprint")
        if evidence not in EVIDENCE_TYPES:
            die(f"{path}: claim {index} has evidence_type '{evidence}'; expected one of {sorted(EVIDENCE_TYPES)}")
        if provenance not in PROVENANCE:
            die(f"{path}: claim {index} has provenance '{provenance}'; expected one of {sorted(PROVENANCE)}")
        span = claim.get("source_span") or None
        claim_id = sha256_text(f"{run_id}|{index}")[:16]
        conn.execute(
            "INSERT INTO claims (claim_id, run_id, arxiv_id, claim_index, text,"
            " source_span, evidence_type, provenance) VALUES (?,?,?,?,?,?,?,?)",
            (claim_id, run_id, arxiv_id, index, text, span, evidence, provenance),
        )
        written.append({"claim_id": claim_id, "claim_index": index, "text": text})

    return {"relevance": relevance, "importance": importance, "claims": written}


def ingest_critic(conn, run_id, record, arxiv_id, path) -> dict:
    reader_run_id = require(record, "reader_run_id", path)
    row = conn.execute(
        "SELECT run_id FROM runs WHERE run_id = ? AND role = 'reader'", (reader_run_id,)
    ).fetchone()
    if not row:
        die(f"{path}: reader_run_id '{reader_run_id}' is not a reader run in this database")

    verdicts = record.get("verdicts") or []
    if not isinstance(verdicts, list) or not verdicts:
        die(f"{path}: 'verdicts' must be a non-empty list")

    counts: dict[str, int] = {}
    for position, verdict in enumerate(verdicts):
        status = require(verdict, "status", path)
        if status not in VERDICT_STATUS:
            die(f"{path}: verdict {position} has status '{status}'; expected one of {sorted(VERDICT_STATUS)}")

        claim_id = verdict.get("claim_id")
        if not claim_id:
            if "claim_index" not in verdict:
                die(f"{path}: verdict {position} needs a claim_id or a claim_index")
            found = conn.execute(
                "SELECT claim_id FROM claims WHERE run_id = ? AND claim_index = ?",
                (reader_run_id, int(verdict["claim_index"])),
            ).fetchone()
            if not found:
                die(f"{path}: reader run {reader_run_id} has no claim at index {verdict['claim_index']}")
            claim_id = found["claim_id"]
        else:
            found = conn.execute(
                "SELECT claim_id FROM claims WHERE claim_id = ? AND run_id = ?",
                (claim_id, reader_run_id),
            ).fetchone()
            if not found:
                die(f"{path}: claim_id '{claim_id}' does not belong to reader run {reader_run_id}")

        conn.execute(
            "INSERT INTO verdicts (run_id, claim_id, status, reason) VALUES (?,?,?,?)",
            (run_id, claim_id, status, verdict.get("reason")),
        )
        counts[status] = counts.get(status, 0) + 1

    return {"reader_run_id": reader_run_id, "verdicts": counts}


def cmd_ingest(args) -> int:
    path = Path(args.artifact)
    record = parse_artifact(path)
    digest = sha256_file(path)

    role = record.get("role") or args.role
    if role not in ("reader", "critic"):
        die(f"role must be 'reader' or 'critic'; got {role!r}")
    arxiv_id = str(require(record, "arxiv_id", path)).strip()

    conn = connect(args.db)
    if not conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='runs'"
    ).fetchone():
        die(f"{args.db} has no schema. Run: uv run scripts/db.py init")

    existing = conn.execute(
        "SELECT run_id FROM runs WHERE role = ? AND artifact_sha256 = ?", (role, digest)
    ).fetchone()
    if existing:
        print(
            json.dumps(
                {"status": "already_ingested", "run_id": existing["run_id"], "artifact": str(path)},
                indent=2,
            )
        )
        conn.close()
        return 0

    run_id = args.run_id or f"{role[:1]}-{uuid.uuid4().hex[:12]}"
    version = version_for(role, args.model, Path(args.agent_file) if args.agent_file else None)

    try:
        with conn:  # one transaction; a failure anywhere leaves the database untouched
            ensure_paper(conn, record, arxiv_id, args.allow_new_paper)
            insert_run(conn, run_id, record, arxiv_id, role, version, args.model, path, digest)
            if role == "reader":
                detail = ingest_reader(conn, run_id, record, arxiv_id, path)
            else:
                detail = ingest_critic(conn, run_id, record, arxiv_id, path)
    except sqlite3.IntegrityError as exc:
        die(f"{path}: database rejected the record: {exc}")
    finally:
        pass

    conn.close()
    print(
        json.dumps(
            {
                "status": "ingested",
                "run_id": run_id,
                "role": role,
                "arxiv_id": arxiv_id,
                "version": version,
                "artifact": str(path),
                "artifact_sha256": digest,
                **detail,
            },
            indent=2,
        )
    )
    return 0


# ------------------------------------------------------------------------------- cli

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="db.py", description="SQLite store for arxiv-triage runs, claims, and judgments."
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"database path (default: {DEFAULT_DB})")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="create the schema (safe to re-run)")
    p_init.set_defaults(func=cmd_init)

    p_ing = sub.add_parser("ingest", help="validate and store one agent artifact")
    p_ing.add_argument("artifact", help="path to the .md or .json the agent wrote")
    p_ing.add_argument("--model", required=True, help="model id the agent ran on, e.g. claude-opus-5")
    p_ing.add_argument("--role", choices=["reader", "critic"], help="override the role in the record")
    p_ing.add_argument("--agent-file", help="agent definition to hash for the version")
    p_ing.add_argument("--run-id", help="use this run id instead of generating one")
    p_ing.add_argument(
        "--allow-new-paper",
        action="store_true",
        help="insert a stub paper row if the paper is not in the database yet",
    )
    p_ing.set_defaults(func=cmd_ingest)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
