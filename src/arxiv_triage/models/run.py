"""Physical agent-run, validation, outcome, and trace contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import model_validator

from .base import (
    ContractModel,
    Identifier,
    NonNegativeInt,
    NonNegativeNumber,
    PositiveInt,
    RepositoryRelativePath,
    Sha256,
    Text,
    UtcTimestamp,
)


Role = Literal["paper_reader", "critic", "reviewer"]
JobType = Literal["paper_read", "paper_critique", "corpus_review"]
AgentRunStatus = Literal[
    "running", "output_received", "invalid", "completed", "failed", "interrupted"
]
TerminalRunStatus = Literal["invalid", "completed", "failed", "interrupted"]
TraceEventType = Literal[
    "agent_run.started",
    "agent_run.output_received",
    "agent_run.invalid",
    "agent_run.completed",
    "agent_run.failed",
    "agent_run.reconciled",
]


def _check_job_scope(
    *, role: Role, job_type: JobType, paper_id: str | None
) -> None:
    expected_job = {
        "paper_reader": "paper_read",
        "critic": "paper_critique",
        "reviewer": "corpus_review",
    }
    if job_type != expected_job[role]:
        raise ValueError("role and job_type do not match")
    if role in {"paper_reader", "critic"} and paper_id is None:
        raise ValueError("paper reader and critic runs require paper_id")
    if role == "reviewer" and paper_id is not None:
        raise ValueError("corpus-scoped runs require paper_id null")


def _as_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value[:-1] + "+00:00")


def _check_path_hash_pair(
    *, path: str | None, digest: str | None, name: str
) -> None:
    if (path is None) != (digest is None):
        raise ValueError(f"{name}_path and {name}_hash must both be set or null")


class AgentRun(ContractModel):
    """Complete mutable projection of one physical invocation."""

    schema_version: Literal["2.0"]
    agent_run_id: Identifier
    investigation_id: Identifier
    paper_id: Identifier | None
    role: Role
    job_type: JobType
    attempt_no: PositiveInt
    status: AgentRunStatus
    model: Text
    agent_definition_hash: Sha256
    component_skill_hash: Sha256 | None
    objective_profile_hash: Sha256 | None
    input_path: RepositoryRelativePath
    input_hash: Sha256
    raw_output_path: RepositoryRelativePath | None
    raw_output_hash: Sha256 | None
    validation_path: RepositoryRelativePath | None
    validation_hash: Sha256 | None
    canonical_path: RepositoryRelativePath | None
    canonical_hash: Sha256 | None
    started_at: UtcTimestamp
    completed_at: UtcTimestamp | None
    duration_ms: NonNegativeInt | None
    tokens_in: NonNegativeInt | None
    tokens_out: NonNegativeInt | None
    cost_usd: NonNegativeNumber | None
    error: Text | None

    @model_validator(mode="after")
    def lifecycle_is_consistent(self) -> Self:
        _check_job_scope(role=self.role, job_type=self.job_type, paper_id=self.paper_id)
        if self.attempt_no > 2:
            raise ValueError("attempt_no must be 1 or 2")
        _check_path_hash_pair(
            path=self.raw_output_path, digest=self.raw_output_hash, name="raw_output"
        )
        _check_path_hash_pair(
            path=self.validation_path, digest=self.validation_hash, name="validation"
        )
        _check_path_hash_pair(
            path=self.canonical_path, digest=self.canonical_hash, name="canonical"
        )
        terminal = self.status in {"invalid", "completed", "failed", "interrupted"}
        if terminal != (self.completed_at is not None and self.duration_ms is not None):
            raise ValueError("terminal runs require completion time and duration only")
        if self.completed_at is not None and _as_datetime(
            self.completed_at
        ) < _as_datetime(self.started_at):
            raise ValueError("completed_at cannot precede started_at")

        if self.status == "running":
            if any(
                value is not None
                for value in (
                    self.raw_output_path,
                    self.validation_path,
                    self.canonical_path,
                    self.error,
                )
            ):
                raise ValueError("running run cannot have output, validation, canonical, or error")
        elif self.status == "output_received":
            if self.raw_output_path is None:
                raise ValueError("output_received run requires raw output")
            if self.validation_path is not None or self.canonical_path is not None or self.error:
                raise ValueError("output_received run cannot be validated or terminal")
        elif self.status == "completed":
            if any(
                value is None
                for value in (
                    self.raw_output_path,
                    self.validation_path,
                    self.canonical_path,
                )
            ):
                raise ValueError("completed run requires raw, validation, and canonical artifacts")
            if self.error is not None:
                raise ValueError("completed run cannot contain an error")
        elif self.status == "invalid":
            if self.raw_output_path is None or self.validation_path is None:
                raise ValueError("invalid run requires raw output and validation artifacts")
            if self.canonical_path is not None or self.error is None:
                raise ValueError("invalid run requires an error and cannot be canonical")
        elif self.status == "failed":
            if any(
                value is not None
                for value in (
                    self.raw_output_path,
                    self.validation_path,
                    self.canonical_path,
                )
            ) or self.error is None:
                raise ValueError("failed run has no returned artifacts and requires an error")
        elif self.canonical_path is not None or self.error is None:
            raise ValueError("interrupted run requires an error and cannot be canonical")
        return self


class ValidationCheck(ContractModel):
    check_id: Identifier
    status: Literal["passed", "failed"]
    detail: Text | None

    @model_validator(mode="after")
    def failed_check_has_detail(self) -> Self:
        if self.status == "failed" and self.detail is None:
            raise ValueError("failed validation check requires detail")
        return self


class ReferencedHash(ContractModel):
    name: Identifier
    sha256: Sha256


class ValidationRecord(ContractModel):
    """Exact ``validation.json`` payload."""

    schema_version: Literal["2.0"]
    agent_run_id: Identifier
    validator_version: Text
    checked_at: UtcTimestamp
    input_hash: Sha256
    parsed_hash: Sha256 | None
    checks: list[ValidationCheck]
    errors: list[Text]
    referenced_hashes: list[ReferencedHash]

    @property
    def validation_passed(self) -> bool:
        return not self.errors

    @model_validator(mode="after")
    def result_is_consistent(self) -> Self:
        if not self.checks:
            raise ValueError("validation record requires at least one check")
        check_ids = [check.check_id for check in self.checks]
        if len(check_ids) != len(set(check_ids)):
            raise ValueError("validation check_id values must be unique")
        names = [item.name for item in self.referenced_hashes]
        if len(names) != len(set(names)):
            raise ValueError("referenced hash names must be unique")
        failed = any(check.status == "failed" for check in self.checks)
        if failed != bool(self.errors):
            raise ValueError("errors must be non-empty exactly when a check failed")
        if not failed and self.parsed_hash is None:
            raise ValueError("successful validation requires parsed_hash")
        return self


class OutcomeRecord(ContractModel):
    """Exact terminal ``outcome.json`` payload."""

    schema_version: Literal["2.0"]
    agent_run_id: Identifier
    status: TerminalRunStatus
    started_at: UtcTimestamp
    completed_at: UtcTimestamp
    duration_ms: NonNegativeInt
    input_path: RepositoryRelativePath
    input_hash: Sha256
    raw_output_path: RepositoryRelativePath | None
    raw_output_hash: Sha256 | None
    validation_path: RepositoryRelativePath | None
    validation_hash: Sha256 | None
    canonical_path: RepositoryRelativePath | None
    canonical_hash: Sha256 | None
    tokens_in: NonNegativeInt | None
    tokens_out: NonNegativeInt | None
    cost_usd: NonNegativeNumber | None
    error: Text | None

    @model_validator(mode="after")
    def outcome_is_consistent(self) -> Self:
        if _as_datetime(self.completed_at) < _as_datetime(self.started_at):
            raise ValueError("completed_at cannot precede started_at")
        _check_path_hash_pair(
            path=self.raw_output_path, digest=self.raw_output_hash, name="raw_output"
        )
        _check_path_hash_pair(
            path=self.validation_path, digest=self.validation_hash, name="validation"
        )
        _check_path_hash_pair(
            path=self.canonical_path, digest=self.canonical_hash, name="canonical"
        )
        if self.status == "completed":
            if any(
                value is None
                for value in (
                    self.raw_output_path,
                    self.validation_path,
                    self.canonical_path,
                )
            ) or self.error is not None:
                raise ValueError("completed outcome requires all artifacts and no error")
        elif self.status == "invalid":
            if self.raw_output_path is None or self.validation_path is None:
                raise ValueError("invalid outcome requires raw output and validation")
            if self.canonical_path is not None or self.error is None:
                raise ValueError("invalid outcome requires an error and no canonical artifact")
        elif self.status == "failed":
            if any(
                value is not None
                for value in (
                    self.raw_output_path,
                    self.validation_path,
                    self.canonical_path,
                )
            ) or self.error is None:
                raise ValueError("failed outcome has no returned artifacts and requires an error")
        elif self.canonical_path is not None or self.error is None:
            raise ValueError("interrupted outcome requires an error and no canonical artifact")
        return self


class TraceEvent(ContractModel):
    schema_version: Literal["2.0"]
    event_id: Identifier
    event_type: TraceEventType
    timestamp: UtcTimestamp
    agent_run_id: Identifier
    investigation_id: Identifier
    paper_id: Identifier | None
    role: Role
    job_type: JobType
    attempt_no: PositiveInt
    sequence: PositiveInt
    model: Text
    agent_definition_hash: Sha256
    component_skill_hash: Sha256 | None
    objective_profile_hash: Sha256 | None
    input_path: RepositoryRelativePath
    input_hash: Sha256
    artifact_path: RepositoryRelativePath | None
    artifact_hash: Sha256 | None
    tokens_in: NonNegativeInt | None
    tokens_out: NonNegativeInt | None
    cost_usd: NonNegativeNumber | None
    error: Text | None

    @model_validator(mode="after")
    def event_is_consistent(self) -> Self:
        _check_job_scope(role=self.role, job_type=self.job_type, paper_id=self.paper_id)
        if self.attempt_no > 2:
            raise ValueError("attempt_no must be 1 or 2")
        _check_path_hash_pair(
            path=self.artifact_path, digest=self.artifact_hash, name="artifact"
        )
        if self.event_type == "agent_run.started":
            if self.sequence != 1:
                raise ValueError("agent_run.started must have sequence 1")
            if self.artifact_path is not None or self.error is not None:
                raise ValueError("started event cannot contain artifact or error")
        elif self.event_type == "agent_run.output_received":
            if self.artifact_path is not None or self.error is not None:
                raise ValueError(
                    "output_received event cannot contain canonical artifact or error"
                )
        elif self.event_type in {"agent_run.completed", "agent_run.reconciled"}:
            if self.artifact_path is None or self.error is not None:
                raise ValueError("completion event requires artifact and no error")
        elif self.artifact_path is not None or self.error is None:
            raise ValueError("invalid and failed events require an error and no artifact")
        return self


__all__ = [
    "AgentRun",
    "AgentRunStatus",
    "JobType",
    "OutcomeRecord",
    "ReferencedHash",
    "Role",
    "TerminalRunStatus",
    "TraceEvent",
    "TraceEventType",
    "ValidationCheck",
    "ValidationRecord",
]
