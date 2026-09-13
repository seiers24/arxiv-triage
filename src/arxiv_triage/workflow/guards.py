"""Pure mechanical guards for dispatch, retry, barriers, and recovery."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Iterable, Mapping

from .state import PAPER_TERMINAL_STATES, PaperState


MAX_AGENT_ATTEMPTS = 2


class GuardViolation(ValueError):
    """Raised when an intent-level workflow operation is mechanically ineligible."""


class JobType(StrEnum):
    PAPER_READ = "paper_read"
    PAPER_CRITIQUE = "paper_critique"
    CORPUS_REVIEW = "corpus_review"


class FailureKind(StrEnum):
    TRANSPORT = "transport"
    MISSING_OUTPUT = "missing_output"
    MALFORMED_JSON = "malformed_json"
    SCHEMA_VALIDATION = "schema_validation"
    SEMANTIC_OBJECTION = "semantic_objection"
    UNSUPPORTED = "unsupported"
    OVERCLAIMED = "overclaimed"
    UNCERTAIN = "uncertain"


RETRYABLE_FAILURE_KINDS = frozenset(
    {
        FailureKind.TRANSPORT,
        FailureKind.MISSING_OUTPUT,
        FailureKind.MALFORMED_JSON,
        FailureKind.SCHEMA_VALIDATION,
    }
)


@dataclass(frozen=True, slots=True)
class LogicalJobKey:
    """The deterministic identity of the one logical job for a scope."""

    investigation_id: str
    job_type: JobType
    paper_id: str | None

    def __post_init__(self) -> None:
        if not self.investigation_id:
            raise GuardViolation("investigation_id must not be empty")
        if self.job_type is JobType.CORPUS_REVIEW:
            if self.paper_id is not None:
                raise GuardViolation("corpus-review jobs must have paper_id=None")
        elif not self.paper_id:
            raise GuardViolation("paper reader and critic jobs require paper_id")


@dataclass(frozen=True, slots=True)
class JobAttempt:
    key: LogicalJobKey
    attempt_no: int

    def __post_init__(self) -> None:
        if not 1 <= self.attempt_no <= MAX_AGENT_ATTEMPTS:
            raise GuardViolation(
                f"attempt_no must be between 1 and {MAX_AGENT_ATTEMPTS}"
            )


@dataclass(frozen=True, slots=True)
class RetryDecision:
    eligible: bool
    next_attempt_no: int | None
    reason: str


def next_attempt(
    *,
    key: LogicalJobKey,
    prior_attempts: Iterable[JobAttempt],
    failure_kind: FailureKind | None,
    canonical_exists: bool,
) -> RetryDecision:
    """Return whether another physical attempt may serve the same logical job.

    Attempt one is eligible only before any attempt exists. Later attempts require
    a retryable physical failure. Valid semantic outcomes never authorize retry.
    """

    attempts = tuple(prior_attempts)
    scoped = [attempt for attempt in attempts if attempt.key == key]

    identities = {(attempt.key, attempt.attempt_no) for attempt in attempts}
    if len(identities) != len(attempts):
        raise GuardViolation("duplicate physical attempt identity")
    if canonical_exists:
        return RetryDecision(False, None, "canonical artifact already exists")
    if not scoped:
        if failure_kind is not None:
            raise GuardViolation("failure_kind is invalid before the first attempt")
        return RetryDecision(True, 1, "initial physical attempt")

    attempt_numbers = sorted(attempt.attempt_no for attempt in scoped)
    if attempt_numbers != list(range(1, len(attempt_numbers) + 1)):
        raise GuardViolation("attempt numbers must be contiguous and start at one")
    if failure_kind is None:
        raise GuardViolation("a later attempt requires a classified prior failure")
    if failure_kind not in RETRYABLE_FAILURE_KINDS:
        return RetryDecision(False, None, "valid semantic outcomes are not retryable")
    if len(scoped) >= MAX_AGENT_ATTEMPTS:
        return RetryDecision(False, None, "physical attempt limit exhausted")
    return RetryDecision(True, len(scoped) + 1, "bounded correction retry")


def ensure_single_logical_job_scope(keys: Iterable[LogicalJobKey]) -> None:
    """Reject duplicate logical jobs for one investigation/role scope.

    Call this with logical jobs, not their physical attempts. Retries reuse the
    same ``LogicalJobKey`` and are checked separately by :func:`next_attempt`.
    """

    seen: set[LogicalJobKey] = set()
    for key in keys:
        if key in seen:
            raise GuardViolation("more than one logical job exists for the same scope")
        seen.add(key)


def ensure_reader_dispatch_eligible(
    *,
    paper_state: PaperState,
    source_files_verified: bool,
    source_hashes_verified: bool,
    canonical_reader_exists: bool,
) -> None:
    if paper_state is not PaperState.SOURCE_FROZEN:
        raise GuardViolation("reader preparation requires source_frozen paper state")
    if not source_files_verified or not source_hashes_verified:
        raise GuardViolation("reader preparation requires verified frozen source bytes")
    if canonical_reader_exists:
        raise GuardViolation("canonical reader artifact already exists")


def ensure_critic_dispatch_eligible(
    *,
    paper_state: PaperState,
    source_hashes_verified: bool,
    canonical_reader_verified: bool,
    canonical_critic_exists: bool,
) -> None:
    if paper_state is not PaperState.READER_VALIDATED:
        raise GuardViolation("critic preparation requires reader_validated paper state")
    if not source_hashes_verified or not canonical_reader_verified:
        raise GuardViolation("critic preparation requires verified source and reader hashes")
    if canonical_critic_exists:
        raise GuardViolation("canonical critic artifact already exists")


@dataclass(frozen=True, slots=True)
class Accounting:
    expected: int
    complete: int
    unresolved: int
    failed: int

    def __post_init__(self) -> None:
        if min(self.expected, self.complete, self.unresolved, self.failed) < 0:
            raise GuardViolation("accounting values must be non-negative")

    @property
    def terminal_total(self) -> int:
        return self.complete + self.unresolved + self.failed


def ensure_reviewer_barrier(
    *,
    included_paper_states: Mapping[str, PaperState],
    accounting: Accounting,
) -> None:
    if len(included_paper_states) != accounting.expected:
        raise GuardViolation("paper-state count does not equal expected corpus count")
    nonterminal = {
        paper_id: state
        for paper_id, state in included_paper_states.items()
        if state not in PAPER_TERMINAL_STATES
    }
    if nonterminal:
        raise GuardViolation(
            "reviewer requires all included papers terminal: "
            + ", ".join(f"{paper_id}={state.value}" for paper_id, state in nonterminal.items())
        )
    observed = Counter(included_paper_states.values())
    expected_counts = {
        PaperState.COMPLETE: accounting.complete,
        PaperState.UNRESOLVED: accounting.unresolved,
        PaperState.FAILED: accounting.failed,
    }
    if accounting.terminal_total != accounting.expected:
        raise GuardViolation("terminal accounting does not equal expected corpus count")
    for state, expected in expected_counts.items():
        if observed[state] != expected:
            raise GuardViolation(
                f"accounting mismatch for {state.value}: expected {expected}, "
                f"observed {observed[state]}"
            )


@dataclass(frozen=True, slots=True)
class ConcurrencyConfig:
    max_concurrent_papers: int
    max_concurrent_fetches: int
    max_concurrent_agents: int

    def __post_init__(self) -> None:
        values = MappingProxyType(
            {
                "max_concurrent_papers": self.max_concurrent_papers,
                "max_concurrent_fetches": self.max_concurrent_fetches,
                "max_concurrent_agents": self.max_concurrent_agents,
            }
        )
        for field, value in values.items():
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise GuardViolation(f"{field} must be a positive integer")


class RecoveryAction(StrEnum):
    NONE = "none"
    MARK_INTERRUPTED_RETRY_ELIGIBLE = "mark_interrupted_retry_eligible"
    MARK_INTERRUPTED_RETRY_EXHAUSTED = "mark_interrupted_retry_exhausted"
    APPEND_RECONCILED_EVENT = "append_reconciled_event"
    REINDEX_SQLITE = "reindex_sqlite"
    INTEGRITY_ERROR = "integrity_error"


@dataclass(frozen=True, slots=True)
class RecoverySnapshot:
    """Read-only evidence used to decide a recovery action.

    The caller performs all filesystem, trace, and SQLite mutations. The two
    ``sqlite_support_*`` fields explicitly describe whether an existing row has
    its required backing evidence, avoiding assumptions about the row's status.
    """

    attempt_no: int
    start_event_exists: bool
    outcome_exists: bool
    validation_passed: bool
    canonical_artifact_exists: bool
    completion_event_exists: bool
    sqlite_row_exists: bool
    hashes_verified: bool
    sqlite_support_artifact_exists: bool = True
    sqlite_support_trace_exists: bool = True

    def __post_init__(self) -> None:
        if not 1 <= self.attempt_no <= MAX_AGENT_ATTEMPTS:
            raise GuardViolation(
                f"attempt_no must be between 1 and {MAX_AGENT_ATTEMPTS}"
            )


def recovery_actions(snapshot: RecoverySnapshot) -> tuple[RecoveryAction, ...]:
    """Classify the specified crash-recovery cases without mutating state."""

    if snapshot.sqlite_row_exists and (
        not snapshot.sqlite_support_artifact_exists
        or not snapshot.sqlite_support_trace_exists
    ):
        return (RecoveryAction.INTEGRITY_ERROR,)

    if snapshot.completion_event_exists and (
        not snapshot.canonical_artifact_exists or not snapshot.hashes_verified
    ):
        return (RecoveryAction.INTEGRITY_ERROR,)

    actions: list[RecoveryAction] = []
    if (
        snapshot.validation_passed
        and snapshot.canonical_artifact_exists
        and not snapshot.completion_event_exists
    ):
        if not snapshot.hashes_verified:
            return (RecoveryAction.INTEGRITY_ERROR,)
        actions.append(RecoveryAction.APPEND_RECONCILED_EVENT)
    elif snapshot.start_event_exists and not snapshot.outcome_exists:
        action = (
            RecoveryAction.MARK_INTERRUPTED_RETRY_ELIGIBLE
            if snapshot.attempt_no < MAX_AGENT_ATTEMPTS
            else RecoveryAction.MARK_INTERRUPTED_RETRY_EXHAUSTED
        )
        actions.append(action)

    if snapshot.completion_event_exists and not snapshot.sqlite_row_exists:
        actions.append(RecoveryAction.REINDEX_SQLITE)

    return tuple(actions) or (RecoveryAction.NONE,)
