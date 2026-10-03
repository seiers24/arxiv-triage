"""Deterministic storage primitives for versioned investigations.

The modules in this package do not validate research semantics.  They persist
already-validated mappings, maintain the append-only execution ledger, and
project authoritative artifacts into a rebuildable SQLite index.
"""

from .artifacts import (
    ArtifactCollisionError,
    ArtifactRef,
    ArtifactStore,
    RunBundlePaths,
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
    sha256_json,
)
from .sqlite import INDEX_SCHEMA_VERSION, SQLiteIndex, StorageSchemaError
from .project import project_repository
from .trace import TraceAppender, TraceFormatError, event_idempotency_key, iter_trace

__all__ = [
    "ArtifactCollisionError",
    "ArtifactRef",
    "ArtifactStore",
    "INDEX_SCHEMA_VERSION",
    "RunBundlePaths",
    "SQLiteIndex",
    "StorageSchemaError",
    "TraceAppender",
    "TraceFormatError",
    "canonical_json_bytes",
    "event_idempotency_key",
    "iter_trace",
    "project_repository",
    "sha256_bytes",
    "sha256_file",
    "sha256_json",
]
