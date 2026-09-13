"""Atomic, immutable artifact persistence.

Paths accepted by :class:`ArtifactStore` are repository-relative POSIX paths.
The store deliberately does not know about Pydantic models: callers must
validate objects before handing their canonical mapping or bytes to storage.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


class ArtifactError(RuntimeError):
    """Base class for artifact persistence failures."""


class ArtifactCollisionError(ArtifactError):
    """Raised when immutable artifact bytes already exist and differ."""


class UnsafeArtifactPathError(ArtifactError):
    """Raised when a path is absolute or escapes the repository root."""


def _json_compatible(value: Any) -> Any:
    """Return a JSON-compatible value without importing the model layer."""

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    return value


def canonical_json_bytes(value: Mapping[str, Any] | Any) -> bytes:
    """Serialize one value in the contract's stable JSON form.

    Canonical JSON is UTF-8, key-sorted, compact, Unicode-preserving, and has
    no trailing newline.  NaN and infinities are rejected because they are not
    valid JSON contract values.
    """

    text = json.dumps(
        _json_compatible(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return text.encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_json(value: Mapping[str, Any] | Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    path: str
    sha256: str
    size_bytes: int
    created: bool


@dataclass(frozen=True, slots=True)
class RunBundlePaths:
    """Canonical paths for one immutable physical model invocation."""

    directory: str
    input: str
    raw_output: str
    parsed: str
    validation: str
    outcome: str


class ArtifactStore:
    """Persist immutable artifacts beneath one repository root."""

    def __init__(self, repository_root: Path | str) -> None:
        self.root = Path(repository_root).resolve()

    def resolve(self, relative_path: str | PurePosixPath) -> Path:
        pure = PurePosixPath(str(relative_path))
        if pure.is_absolute() or ".." in pure.parts or not pure.parts:
            raise UnsafeArtifactPathError(
                f"artifact path must be repository-relative without '..': {relative_path}"
            )
        candidate = self.root.joinpath(*pure.parts).resolve(strict=False)
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise UnsafeArtifactPathError(
                f"artifact path escapes repository root: {relative_path}"
            ) from exc
        return candidate

    def relative(self, path: Path | str) -> str:
        candidate = Path(path).resolve(strict=False)
        try:
            return candidate.relative_to(self.root).as_posix()
        except ValueError as exc:
            raise UnsafeArtifactPathError(
                f"path is outside repository root: {path}"
            ) from exc

    def run_bundle(self, investigation_id: str, agent_run_id: str) -> RunBundlePaths:
        base = PurePosixPath("data/investigations") / investigation_id / "runs" / agent_run_id
        return RunBundlePaths(
            directory=base.as_posix(),
            input=(base / "input.json").as_posix(),
            raw_output=(base / "raw-output.txt").as_posix(),
            parsed=(base / "parsed.json").as_posix(),
            validation=(base / "validation.json").as_posix(),
            outcome=(base / "outcome.json").as_posix(),
        )

    def write_bytes(self, relative_path: str, data: bytes) -> ArtifactRef:
        """Atomically create an immutable artifact.

        A byte-identical repeat is idempotent.  Different bytes at the same
        path are a collision and are never overwritten.
        """

        target = self.resolve(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            existing = target.read_bytes()
            if existing != data:
                raise ArtifactCollisionError(
                    f"immutable artifact already exists with different bytes: {relative_path}"
                )
            return ArtifactRef(relative_path, sha256_bytes(existing), len(existing), False)

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())

            # Linking the durable sibling into place is an atomic
            # create-if-absent operation. Unlike os.replace(), it cannot
            # overwrite bytes created by a concurrent writer between the
            # existence check above and this visibility point.
            try:
                os.link(temporary, target)
            except FileExistsError:
                existing = target.read_bytes()
                if existing != data:
                    raise ArtifactCollisionError(
                        "immutable artifact already exists with different bytes: "
                        f"{relative_path}"
                    )
                self._fsync_directory(target.parent)
                return ArtifactRef(
                    relative_path,
                    sha256_bytes(existing),
                    len(existing),
                    False,
                )
            self._fsync_directory(target.parent)
            return ArtifactRef(relative_path, sha256_bytes(data), len(data), True)
        finally:
            temporary.unlink(missing_ok=True)

    def write_text(self, relative_path: str, text: str) -> ArtifactRef:
        return self.write_bytes(relative_path, text.encode("utf-8"))

    def write_json(self, relative_path: str, value: Mapping[str, Any] | Any) -> ArtifactRef:
        return self.write_bytes(relative_path, canonical_json_bytes(value))

    def copy_exact(self, source_path: str, destination_path: str) -> ArtifactRef:
        return self.write_bytes(destination_path, self.resolve(source_path).read_bytes())

    def promote_parsed(
        self,
        parsed_path: str,
        canonical_path: str,
        *,
        expected_input_hash: str,
    ) -> ArtifactRef:
        """Promote validated parsed bytes to a canonical role artifact.

        The caller performs schema and cross-artifact validation.  This final
        storage guard ensures the parsed artifact is one JSON object bound to
        the validated input before copying its exact bytes.
        """

        parsed_bytes = self.resolve(parsed_path).read_bytes()
        try:
            payload = json.loads(parsed_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ArtifactError(f"parsed artifact is not valid UTF-8 JSON: {parsed_path}") from exc
        if not isinstance(payload, dict):
            raise ArtifactError(f"parsed artifact must contain one JSON object: {parsed_path}")
        if payload.get("input_hash") != expected_input_hash:
            raise ArtifactError(
                f"parsed artifact input_hash does not match validated input: {parsed_path}"
            )
        return self.write_bytes(canonical_path, parsed_bytes)

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
