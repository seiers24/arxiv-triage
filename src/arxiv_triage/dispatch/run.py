"""Durable execution of one bounded physical worker attempt."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from pydantic import BaseModel

from arxiv_triage.models import (
    AgentRun,
    OutcomeRecord,
    ReferencedHash,
    TraceEvent,
    ValidationCheck,
    ValidationRecord,
)
from arxiv_triage.storage import ArtifactStore, SQLiteIndex, TraceAppender

from .base import WorkerDispatcher


Validator = Callable[[Any, bytes], BaseModel]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


@dataclass(frozen=True, slots=True)
class RunContext:
    investigation_id: str
    paper_id: str | None
    screening_batch_id: str | None
    role: str
    job_type: str
    attempt_no: int
    model: str
    agent_definition_hash: str
    component_skill_hash: str | None
    objective_profile_hash: str | None
    canonical_path: str
    referenced_hashes: tuple[ReferencedHash, ...] = ()


@dataclass(frozen=True, slots=True)
class RunExecutionResult:
    run: AgentRun
    canonical_record: BaseModel | None


class RunExecutor:
    """Persist, validate, trace, and optionally index one invocation."""

    def __init__(
        self,
        repository_root: str,
        *,
        trace_path: str = "logs/trace.jsonl",
        index: SQLiteIndex | None = None,
        validator_version: str = "arxiv-triage-2.0",
    ) -> None:
        self.store = ArtifactStore(repository_root)
        self.trace = TraceAppender(self.store.resolve(trace_path))
        self.index = index
        self.validator_version = validator_version

    def execute(
        self,
        *,
        task: BaseModel,
        context: RunContext,
        validator: Validator,
        dispatcher: WorkerDispatcher,
    ) -> RunExecutionResult:
        agent_run_id = getattr(task, "agent_run_id")
        input_hash = getattr(task, "input_hash")
        if context.investigation_id != getattr(task, "investigation_id"):
            raise ValueError("run context investigation_id does not match task")
        if context.job_type != getattr(task, "job_type"):
            raise ValueError("run context job_type does not match task")

        bundle = self.store.run_bundle(context.investigation_id, agent_run_id)
        self.store.write_json(bundle.input, task)
        started_at = _now()
        started_clock = time.monotonic_ns()
        running = self._run(
            task=task,
            context=context,
            status="running",
            started_at=started_at,
            input_path=bundle.input,
        )
        self._index(running)
        self.trace.append(self._event(running, "agent_run.started", 1))

        try:
            response = dispatcher.dispatch(task)
        except Exception as exc:
            completed_at, duration_ms = self._completion(started_clock)
            failed = self._run(
                task=task,
                context=context,
                status="failed",
                started_at=started_at,
                input_path=bundle.input,
                completed_at=completed_at,
                duration_ms=duration_ms,
                error=f"{type(exc).__name__}: {exc}",
            )
            self.store.write_json(bundle.outcome, self._outcome_payload(failed))
            self.trace.append(self._event(failed, "agent_run.failed", 2))
            self._index(failed)
            return RunExecutionResult(failed, None)

        raw_ref = self.store.write_bytes(bundle.raw_output, response.raw_output)
        received = AgentRun.model_validate(
            running.model_copy(
                update={
                    "status": "output_received",
                    "raw_output_path": bundle.raw_output,
                    "raw_output_hash": raw_ref.sha256,
                    "tokens_in": response.tokens_in,
                    "tokens_out": response.tokens_out,
                    "cost_usd": response.cost_usd,
                }
            ).model_dump(mode="json")
        )
        self.trace.append(self._event(received, "agent_run.output_received", 2))
        self._index(received)
        checked_at = _now()
        try:
            canonical_record = validator(task, response.raw_output)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            validation = ValidationRecord(
                schema_version="2.0",
                agent_run_id=agent_run_id,
                validator_version=self.validator_version,
                checked_at=checked_at,
                input_hash=input_hash,
                parsed_hash=None,
                checks=[
                    ValidationCheck(
                        check_id="worker-output", status="failed", detail=error
                    )
                ],
                errors=[error],
                referenced_hashes=list(context.referenced_hashes),
            )
            validation_ref = self.store.write_json(bundle.validation, validation)
            completed_at, duration_ms = self._completion(started_clock)
            invalid = AgentRun.model_validate(
                received.model_copy(
                    update={
                        "status": "invalid",
                        "validation_path": bundle.validation,
                        "validation_hash": validation_ref.sha256,
                        "completed_at": completed_at,
                        "duration_ms": duration_ms,
                        "error": error,
                    }
                ).model_dump(mode="json")
            )
            self.store.write_json(bundle.outcome, self._outcome_payload(invalid))
            self.trace.append(self._event(invalid, "agent_run.invalid", 3))
            self._index(invalid)
            return RunExecutionResult(invalid, None)

        parsed_ref = self.store.write_json(bundle.parsed, canonical_record)
        validation = ValidationRecord(
            schema_version="2.0",
            agent_run_id=agent_run_id,
            validator_version=self.validator_version,
            checked_at=checked_at,
            input_hash=input_hash,
            parsed_hash=parsed_ref.sha256,
            checks=[
                ValidationCheck(
                    check_id="worker-output", status="passed", detail=None
                )
            ],
            errors=[],
            referenced_hashes=list(context.referenced_hashes),
        )
        validation_ref = self.store.write_json(bundle.validation, validation)
        canonical_ref = self.store.promote_parsed(
            bundle.parsed,
            context.canonical_path,
            expected_input_hash=input_hash,
        )
        completed_at, duration_ms = self._completion(started_clock)
        completed = AgentRun.model_validate(
            received.model_copy(
                update={
                    "status": "completed",
                    "validation_path": bundle.validation,
                    "validation_hash": validation_ref.sha256,
                    "canonical_path": canonical_ref.path,
                    "canonical_hash": canonical_ref.sha256,
                    "completed_at": completed_at,
                    "duration_ms": duration_ms,
                    "error": None,
                }
            ).model_dump(mode="json")
        )
        self.store.write_json(bundle.outcome, self._outcome_payload(completed))
        self.trace.append(self._event(completed, "agent_run.completed", 3))
        self._index(completed)
        return RunExecutionResult(completed, canonical_record)

    @staticmethod
    def _completion(started_clock: int) -> tuple[str, int]:
        elapsed = max(0, (time.monotonic_ns() - started_clock) // 1_000_000)
        return _now(), elapsed

    @staticmethod
    def _run(
        *,
        task: BaseModel,
        context: RunContext,
        status: str,
        started_at: str,
        input_path: str,
        completed_at: str | None = None,
        duration_ms: int | None = None,
        error: str | None = None,
    ) -> AgentRun:
        return AgentRun(
            schema_version="2.0",
            agent_run_id=getattr(task, "agent_run_id"),
            investigation_id=context.investigation_id,
            paper_id=context.paper_id,
            screening_batch_id=context.screening_batch_id,
            role=context.role,
            job_type=context.job_type,
            attempt_no=context.attempt_no,
            status=status,
            model=context.model,
            agent_definition_hash=context.agent_definition_hash,
            component_skill_hash=context.component_skill_hash,
            objective_profile_hash=context.objective_profile_hash,
            input_path=input_path,
            input_hash=getattr(task, "input_hash"),
            raw_output_path=None,
            raw_output_hash=None,
            validation_path=None,
            validation_hash=None,
            canonical_path=None,
            canonical_hash=None,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            tokens_in=None,
            tokens_out=None,
            cost_usd=None,
            error=error,
        )

    @staticmethod
    def _outcome_payload(run: AgentRun) -> OutcomeRecord:
        fields = {
            "schema_version",
            "agent_run_id",
            "status",
            "started_at",
            "completed_at",
            "duration_ms",
            "input_path",
            "input_hash",
            "raw_output_path",
            "raw_output_hash",
            "validation_path",
            "validation_hash",
            "canonical_path",
            "canonical_hash",
            "tokens_in",
            "tokens_out",
            "cost_usd",
            "error",
        }
        return OutcomeRecord.model_validate(
            run.model_dump(mode="json", include=fields)
        )

    @staticmethod
    def _event(run: AgentRun, event_type: str, sequence: int) -> TraceEvent:
        completed = event_type == "agent_run.completed"
        failed = event_type in {"agent_run.invalid", "agent_run.failed"}
        return TraceEvent(
            schema_version="2.0",
            event_id=f"evt-{uuid.uuid4().hex}",
            event_type=event_type,
            timestamp=_now(),
            agent_run_id=run.agent_run_id,
            investigation_id=run.investigation_id,
            paper_id=run.paper_id,
            screening_batch_id=run.screening_batch_id,
            role=run.role,
            job_type=run.job_type,
            attempt_no=run.attempt_no,
            sequence=sequence,
            model=run.model,
            agent_definition_hash=run.agent_definition_hash,
            component_skill_hash=run.component_skill_hash,
            objective_profile_hash=run.objective_profile_hash,
            input_path=run.input_path,
            input_hash=run.input_hash,
            artifact_path=run.canonical_path if completed else None,
            artifact_hash=run.canonical_hash if completed else None,
            tokens_in=run.tokens_in,
            tokens_out=run.tokens_out,
            cost_usd=run.cost_usd,
            error=run.error if failed else None,
        )

    def _index(self, run: AgentRun) -> None:
        if self.index is not None:
            self.index.upsert_agent_run(run)


__all__ = ["RunContext", "RunExecutionResult", "RunExecutor"]
