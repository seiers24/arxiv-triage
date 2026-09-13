"""Shared primitives for schema-version 2.0 contracts.

These helpers deliberately validate only guarantees stated by the core
investigation specification. Component-owned objects remain JSON objects and
are validated by their component schemas.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Annotated, Any, Mapping

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
)
from pydantic.functional_validators import BeforeValidator
from pydantic.types import StringConstraints


SCHEMA_VERSION = "2.0"


def _nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("must contain a non-whitespace character")
    return value


def _rfc3339(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("must be an RFC 3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("must include a timezone")
    return value


def _utc_rfc3339(value: str) -> str:
    _rfc3339(value)
    if not value.endswith("Z"):
        raise ValueError("must use the canonical UTC Z suffix")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("must be a UTC timestamp")
    return value


def _repository_relative(value: str) -> str:
    if "\\" in value:
        raise ValueError("must use POSIX path separators")
    if value == ".":
        raise ValueError("must name a repository-relative artifact")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {".", ".."} for part in path.parts):
        raise ValueError("must be a repository-relative path without dot segments")
    if path.as_posix() != value:
        raise ValueError("must be a normalized repository-relative POSIX path")
    return value


def _reject_bool(value: Any) -> Any:
    if isinstance(value, bool):
        raise ValueError("booleans are not integers")
    return value


Text = Annotated[
    str,
    StringConstraints(strict=True, min_length=1),
    AfterValidator(_nonblank),
]
Identifier = Annotated[
    str,
    StringConstraints(
        strict=True,
        pattern=r"^[a-z][a-z0-9]*(?:[-_.:][a-z0-9]+)*$",
    ),
]
Sha256 = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$"),
]
Rfc3339 = Annotated[
    str,
    StringConstraints(strict=True),
    AfterValidator(_rfc3339),
]
UtcTimestamp = Annotated[
    str,
    StringConstraints(
        strict=True,
        pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$",
    ),
    AfterValidator(_utc_rfc3339),
]
RepositoryRelativePath = Annotated[
    str,
    StringConstraints(strict=True, min_length=1),
    AfterValidator(_nonblank),
    AfterValidator(_repository_relative),
]
NonNegativeInt = Annotated[
    StrictInt,
    BeforeValidator(_reject_bool),
    Field(ge=0),
]
PositiveInt = Annotated[
    StrictInt,
    BeforeValidator(_reject_bool),
    Field(gt=0),
]
NonNegativeNumber = Annotated[
    StrictInt | StrictFloat,
    BeforeValidator(_reject_bool),
    Field(ge=0),
]
Score = Annotated[
    StrictInt,
    BeforeValidator(_reject_bool),
    Field(ge=0, le=5),
]

JsonObject = dict[str, Any]


class ContractModel(BaseModel):
    """Strict base configuration for every closed contract object."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


def canonical_json(value: BaseModel | Mapping[str, object]) -> str:
    """Serialize one object deterministically for byte hashing."""

    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else dict(value)
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )


def sha256_bytes(value: bytes) -> str:
    """Return a lowercase hexadecimal SHA-256 digest."""

    return hashlib.sha256(value).hexdigest()


def sha256_json(value: BaseModel | Mapping[str, object]) -> str:
    """Hash the canonical UTF-8 JSON representation of an object."""

    return sha256_bytes(canonical_json(value).encode("utf-8"))


def sha256_self_hash(
    value: BaseModel | Mapping[str, object], hash_field: str
) -> str:
    """Hash a hash-bearing object while excluding only its own hash field."""

    if isinstance(value, BaseModel):
        payload = value.model_dump(mode="json", exclude={hash_field})
    else:
        payload = dict(value)
        if hash_field not in payload:
            raise ValueError(f"self-hash field is missing: {hash_field}")
        del payload[hash_field]
    return sha256_json(payload)


def require_self_hash(value: BaseModel, hash_field: str) -> None:
    """Reject a hash-bearing object whose stored digest is not its self-hash."""

    if getattr(value, hash_field) != sha256_self_hash(value, hash_field):
        raise ValueError(f"{hash_field} does not match canonical object bytes")
