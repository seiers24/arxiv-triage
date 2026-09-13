"""Shared primitives for schema-version 2.0 contracts.

These helpers deliberately validate only guarantees stated by the core
investigation specification. Component-owned objects remain JSON objects and
are validated by their component schemas.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Any, Mapping

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictInt
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


def _reject_bool(value: Any) -> Any:
    if isinstance(value, bool):
        raise ValueError("booleans are not integers")
    return value


Text = Annotated[
    str,
    StringConstraints(strict=True, min_length=1),
    AfterValidator(_nonblank),
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
Score = Annotated[
    StrictInt,
    BeforeValidator(_reject_bool),
    Field(ge=0, le=5),
]

JsonObject = dict[str, Any]


class ContractModel(BaseModel):
    """Strict base configuration for every closed contract object."""

    model_config = ConfigDict(extra="forbid", strict=True)


def canonical_json(value: BaseModel | Mapping[str, object]) -> str:
    """Serialize one object deterministically for byte hashing."""

    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else dict(value)
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def sha256_bytes(value: bytes) -> str:
    """Return a lowercase hexadecimal SHA-256 digest."""

    return hashlib.sha256(value).hexdigest()


def sha256_json(value: BaseModel | Mapping[str, object]) -> str:
    """Hash the canonical UTF-8 JSON representation of an object."""

    return sha256_bytes(canonical_json(value).encode("utf-8"))
