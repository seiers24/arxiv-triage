"""Crash-recovery inspection for run bundles, trace events, and SQLite rows.

Reconciliation is deliberately conservative.  It identifies interrupted runs,
verifies promoted artifact hashes, and reports missing projections.  It never
creates model output or promotes an unvalidated response.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .artifacts import ArtifactStore, sha256_file
from .sqlite import SQLiteIndex
from .trace import TraceAppender, iter_trace


_TERMINAL_EVENT_TYPES = frozenset(
    {
        "agent_run.invalid",
        "agent_run.completed",
        "agent_run.failed",
        "agent_run.reconciled",
    }
)

_STATUS_EVENT_TYPES = {
    "running": frozenset({"agent_run.started"}),
    "output_received": frozenset({"agent_run.output_received"}),
    "invalid": frozenset({"agent_run.invalid"}),
    "completed": frozenset({"agent_run.completed", "agent_run.reconciled"}),
    "failed": frozenset({"agent_run.failed"}),
    # Recovery records interruption in SQLite after a durable start event. The
    # trace contract intentionally has no separate interrupted event.
    "interrupted": frozenset({"agent_run.started"}),
}


@dataclass(frozen=True, slots=True)
class ReconciliationItem:
    agent_run_id: str
    action: str
    detail: str
    canonical_path: str | None = None
    canonical_hash: str | None = None


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    investigation_id: str
    interrupted: tuple[ReconciliationItem, ...]
    append_reconciled: tuple[ReconciliationItem, ...]
    reindex_required: tuple[ReconciliationItem, ...]
    integrity_errors: tuple[ReconciliationItem, ...]

    @property
    def clean(self) -> bool:
        return not (
            self.interrupted
            or self.append_reconciled
            or self.reindex_required
            or self.integrity_errors
        )


class Reconciler:
    def __init__(
        self,
        repository_root: Path | str,
        *,
        trace_path: str = "logs/trace.jsonl",
        index: SQLiteIndex | None = None,
    ) -> None:
        self.store = ArtifactStore(repository_root)
        self.trace_path = self.store.resolve(trace_path)
        self.index = index

    def inspect(self, investigation_id: str) -> ReconciliationReport:
        all_events = [
            event
            for event in iter_trace(self.trace_path)
            if event["investigation_id"] == investigation_id
        ]
        events_by_run: dict[str, list[dict[str, Any]]] = {}
        for event in all_events:
            events_by_run.setdefault(event["agent_run_id"], []).append(event)

        database_rows = (
            {row["agent_run_id"]: row for row in self.index.agent_run_rows()}
            if self.index is not None
            else {}
        )
        run_root = self.store.resolve(
            f"data/investigations/{investigation_id}/runs"
        )
        run_directories = {
            path.name: path for path in run_root.iterdir() if path.is_dir()
        } if run_root.exists() else {}

        interrupted: list[ReconciliationItem] = []
        append_reconciled: list[ReconciliationItem] = []
        reindex_required: list[ReconciliationItem] = []
        integrity_errors: list[ReconciliationItem] = []

        for run_id in sorted(set(events_by_run) | set(run_directories)):
            events = events_by_run.get(run_id, [])
            event_types = {event["event_type"] for event in events}
            terminal_event_types = event_types.intersection(_TERMINAL_EVENT_TYPES)
            run_directory = run_directories.get(run_id)
            outcome_path = run_directory / "outcome.json" if run_directory else None
            outcome = self._read_object(outcome_path) if outcome_path and outcome_path.exists() else None

            if (
                "agent_run.started" in event_types
                and not terminal_event_types
                and outcome is None
            ):
                interrupted.append(
                    ReconciliationItem(
                        run_id,
                        "mark_interrupted",
                        "start event exists but the immutable run bundle has no outcome.json",
                    )
                )
                continue


            if terminal_event_types and outcome is None:
                integrity_errors.append(
                    ReconciliationItem(
                        run_id,
                        "integrity_error",
                        "terminal trace event exists but the immutable run bundle has no outcome.json",
                    )
                )

            canonical_path, canonical_hash = self._verified_canonical(outcome)
            completion_present = bool(
                {"agent_run.completed", "agent_run.reconciled"}.intersection(event_types)
            )
            if canonical_path and not terminal_event_types:
                append_reconciled.append(
                    ReconciliationItem(
                        run_id,
                        "append_reconciled",
                        "validated outcome and canonical artifact exist without completion event",
                        canonical_path,
                        canonical_hash,
                    )
                )
            elif canonical_path and not completion_present:
                integrity_errors.append(
                    ReconciliationItem(
                        run_id,
                        "integrity_error",
                        "canonical outcome conflicts with a non-completion terminal trace event",
                        canonical_path,
                        canonical_hash,
                    )
                )
            if terminal_event_types and outcome is not None and run_id not in database_rows:
                reindex_required.append(
                    ReconciliationItem(
                        run_id,
                        "reindex",
                        "terminal trace event exists but SQLite has no run projection",
                        canonical_path,
                        canonical_hash,
                    )
                )

        for run_id, row in sorted(database_rows.items()):
            if row["investigation_id"] != investigation_id:
                continue
            events = events_by_run.get(run_id, [])
            event_types = {event["event_type"] for event in events}
            canonical_path = row.get("canonical_path")
            missing_trace = not events
            missing_artifact = bool(canonical_path) and not self.store.resolve(canonical_path).is_file()
            expected_events = _STATUS_EVENT_TYPES.get(row["status"], frozenset())
            missing_status_event = bool(events) and not event_types.intersection(expected_events)
            invalid_has_canonical = row["status"] == "invalid" and bool(canonical_path)
            if missing_trace or missing_status_event or missing_artifact or invalid_has_canonical:
                reasons = []
                if missing_trace:
                    reasons.append("no supporting trace event")
                if missing_status_event:
                    reasons.append(
                        f"no trace event supports projected status {row['status']!r}"
                    )
                if missing_artifact:
                    reasons.append("canonical artifact is missing")
                if invalid_has_canonical:
                    reasons.append("invalid attempt references a canonical artifact")
                integrity_errors.append(
                    ReconciliationItem(
                        run_id,
                        "integrity_error",
                        "; ".join(reasons),
                        canonical_path,
                        row.get("canonical_hash"),
                    )
                )

        return ReconciliationReport(
            investigation_id,
            tuple(interrupted),
            tuple(append_reconciled),
            tuple(reindex_required),
            tuple(integrity_errors),
        )

    def apply_safe_repairs(self, report: ReconciliationReport) -> None:
        """Apply only repairs derivable from durable bytes.

        Missing SQLite projections remain caller work because artifact-to-row
        projection requires schema models.  Integrity errors are never hidden.
        """

        if self.index is not None:
            for item in report.interrupted:
                self.index.mark_interrupted(item.agent_run_id)

        events = list(iter_trace(self.trace_path))
        events_by_run: dict[str, list[dict[str, Any]]] = {}
        for event in events:
            events_by_run.setdefault(event["agent_run_id"], []).append(event)

        appender = TraceAppender(self.trace_path)
        for item in report.append_reconciled:
            prior = events_by_run.get(item.agent_run_id, [])
            if not prior:
                continue
            latest = max(prior, key=lambda event: event["sequence"])
            reconciled = dict(latest)
            reconciled.update(
                {
                    "event_id": f"evt-reconciled-{uuid.uuid4().hex}",
                    "event_type": "agent_run.reconciled",
                    "timestamp": datetime.now(timezone.utc)
                    .isoformat(timespec="seconds")
                    .replace("+00:00", "Z"),
                    "sequence": latest["sequence"] + 1,
                    "artifact_path": item.canonical_path,
                    "artifact_hash": item.canonical_hash,
                    "error": None,
                }
            )
            appender.append(reconciled)

    def _verified_canonical(
        self, outcome: dict[str, Any] | None
    ) -> tuple[str | None, str | None]:
        if not outcome:
            return None, None
        validation_passed = outcome.get("validation_pass") is True or outcome.get("status") in {
            "validated",
            "canonicalized",
            "indexed",
            "completed",
        }
        canonical_path = outcome.get("canonical_path") or outcome.get("artifact_path")
        expected_hash = outcome.get("canonical_hash") or outcome.get("artifact_hash")
        if not validation_passed or not isinstance(canonical_path, str):
            return None, None
        path = self.store.resolve(canonical_path)
        if not path.is_file():
            return None, None
        actual_hash = sha256_file(path)
        if not isinstance(expected_hash, str) or actual_hash != expected_hash:
            return None, None
        return canonical_path, actual_hash

    @staticmethod
    def _read_object(path: Path) -> dict[str, Any]:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"run bundle file must contain a JSON object: {path}")
        return value
