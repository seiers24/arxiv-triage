"""Durable append-only lifecycle event ledger."""

from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from .artifacts import canonical_json_bytes


SCHEMA_VERSION = "2.0"
EVENT_TYPES = frozenset(
    {
        "agent_run.started",
        "agent_run.output_received",
        "agent_run.invalid",
        "agent_run.completed",
        "agent_run.failed",
        "agent_run.reconciled",
    }
)

REQUIRED_FIELDS = frozenset(
    {
        "schema_version",
        "event_id",
        "event_type",
        "timestamp",
        "agent_run_id",
        "investigation_id",
        "paper_id",
        "role",
        "job_type",
        "attempt_no",
        "sequence",
        "model",
        "agent_definition_hash",
        "component_skill_hash",
        "objective_profile_hash",
        "input_path",
        "input_hash",
        "artifact_path",
        "artifact_hash",
        "tokens_in",
        "tokens_out",
        "cost_usd",
        "error",
    }
)


class TraceFormatError(ValueError):
    """Raised for a malformed lifecycle event or trace line."""


def validate_event_shape(event: Mapping[str, Any]) -> None:
    """Validate the universal mechanics needed by storage and replay.

    Full schema and cross-artifact validation remains in the model/validation
    layer.  Storage rejects missing lifecycle keys, unsupported versions or
    event types, and unusable idempotency fields.
    """

    missing = REQUIRED_FIELDS.difference(event)
    if missing:
        raise TraceFormatError(f"trace event is missing fields: {sorted(missing)}")
    if event["schema_version"] != SCHEMA_VERSION:
        raise TraceFormatError("trace event schema_version must be '2.0'")
    if event["event_type"] not in EVENT_TYPES:
        raise TraceFormatError(f"unsupported trace event type: {event['event_type']!r}")
    for field in ("event_id", "agent_run_id", "investigation_id", "job_type"):
        if not isinstance(event[field], str) or not event[field].strip():
            raise TraceFormatError(f"trace event {field} must be a nonblank string")
    if type(event["sequence"]) is not int or event["sequence"] < 1:
        raise TraceFormatError("trace event sequence must be a positive integer")
    if type(event["attempt_no"]) is not int or not 1 <= event["attempt_no"] <= 2:
        raise TraceFormatError("trace event attempt_no must be 1 or 2")


def event_idempotency_key(event: Mapping[str, Any]) -> tuple[str, str, str, int]:
    """Return both specification-defined replay identities as one key."""

    validate_event_shape(event)
    return (
        str(event["event_id"]),
        str(event["agent_run_id"]),
        str(event["event_type"]),
        int(event["sequence"]),
    )


class TraceAppender:
    """Append one fsync'd UTF-8 JSON line while holding an advisory lock."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def append(self, event: Mapping[str, Any]) -> None:
        validate_event_shape(event)
        line = canonical_json_bytes(dict(event)) + b"\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("ab", buffering=0) as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                stream.write(line)
                os.fsync(stream.fileno())
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def iter_trace(path: Path | str) -> Iterator[dict[str, Any]]:
    """Yield validated events in append order; reject corrupt or partial lines."""

    trace_path = Path(path)
    if not trace_path.exists():
        return
    with trace_path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise TraceFormatError(
                    f"{trace_path}:{line_number}: invalid JSON trace line"
                ) from exc
            if not isinstance(value, dict):
                raise TraceFormatError(
                    f"{trace_path}:{line_number}: trace line must be an object"
                )
            validate_event_shape(value)
            yield value


def replay_unique(path: Path | str) -> Iterator[dict[str, Any]]:
    """Yield the first occurrence of each replay-idempotency pair."""

    event_ids: set[str] = set()
    lifecycle_keys: set[tuple[str, str, int]] = set()
    for event in iter_trace(path):
        event_id, run_id, event_type, sequence = event_idempotency_key(event)
        lifecycle_key = (run_id, event_type, sequence)
        if event_id in event_ids or lifecycle_key in lifecycle_keys:
            continue
        event_ids.add(event_id)
        lifecycle_keys.add(lifecycle_key)
        yield event
