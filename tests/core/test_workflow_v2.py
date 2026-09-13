from __future__ import annotations

import pytest

from arxiv_triage.workflow import (
    Accounting,
    AgentRunState,
    ConcurrencyConfig,
    FailureKind,
    GuardViolation,
    InvestigationState,
    InvalidTransition,
    JobAttempt,
    JobType,
    LogicalJobKey,
    PaperState,
    RecoveryAction,
    RecoverySnapshot,
    WorkflowService,
    ensure_single_logical_job_scope,
    next_attempt,
    recovery_actions,
    transition_agent_run,
    transition_investigation,
    transition_paper,
)
from arxiv_triage.workflow.service import ReviewReportStatus


def test_legal_state_chains() -> None:
    assert transition_investigation(
        InvestigationState.ANALYZING, InvestigationState.REVIEWING
    ) is InvestigationState.REVIEWING
    assert transition_paper(
        PaperState.READER_VALIDATED, PaperState.CRITIC_PENDING
    ) is PaperState.CRITIC_PENDING
    assert transition_agent_run(
        AgentRunState.VALIDATED, AgentRunState.CANONICALIZED
    ) is AgentRunState.CANONICALIZED


@pytest.mark.parametrize(
    ("transition", "current", "target"),
    [
        (
            transition_investigation,
            InvestigationState.INPUTS_VALIDATED,
            InvestigationState.REVIEWING,
        ),
        (transition_paper, PaperState.SOURCE_FROZEN, PaperState.CRITIC_RUNNING),
        (transition_agent_run, AgentRunState.INVALID, AgentRunState.RUNNING),
    ],
)
def test_illegal_transitions_are_rejected(transition, current, target) -> None:
    with pytest.raises(InvalidTransition):
        transition(current, target)


def test_reader_requires_verified_frozen_source_and_no_canonical() -> None:
    assert WorkflowService.prepare_reader(
        PaperState.SOURCE_FROZEN,
        source_files_verified=True,
        source_hashes_verified=True,
        canonical_reader_exists=False,
    ) is PaperState.READER_PENDING

    with pytest.raises(GuardViolation, match="source_frozen"):
        WorkflowService.prepare_reader(
            PaperState.FETCHING,
            source_files_verified=True,
            source_hashes_verified=True,
            canonical_reader_exists=False,
        )
    with pytest.raises(GuardViolation, match="verified frozen source"):
        WorkflowService.prepare_reader(
            PaperState.SOURCE_FROZEN,
            source_files_verified=False,
            source_hashes_verified=True,
            canonical_reader_exists=False,
        )
    with pytest.raises(GuardViolation, match="already exists"):
        WorkflowService.prepare_reader(
            PaperState.SOURCE_FROZEN,
            source_files_verified=True,
            source_hashes_verified=True,
            canonical_reader_exists=True,
        )


def test_critic_requires_validated_reader_and_no_canonical() -> None:
    assert WorkflowService.prepare_critic(
        PaperState.READER_VALIDATED,
        source_hashes_verified=True,
        canonical_reader_verified=True,
        canonical_critic_exists=False,
    ) is PaperState.CRITIC_PENDING

    with pytest.raises(GuardViolation, match="reader_validated"):
        WorkflowService.prepare_critic(
            PaperState.READER_RUNNING,
            source_hashes_verified=True,
            canonical_reader_verified=True,
            canonical_critic_exists=False,
        )


def test_logical_job_has_at_most_two_contiguous_physical_attempts() -> None:
    key = LogicalJobKey("inv-1", JobType.PAPER_READ, "paper-1")
    first = next_attempt(
        key=key, prior_attempts=(), failure_kind=None, canonical_exists=False
    )
    assert first.eligible and first.next_attempt_no == 1

    second = next_attempt(
        key=key,
        prior_attempts=(JobAttempt(key, 1),),
        failure_kind=FailureKind.MALFORMED_JSON,
        canonical_exists=False,
    )
    assert second.eligible and second.next_attempt_no == 2

    exhausted = next_attempt(
        key=key,
        prior_attempts=(JobAttempt(key, 1), JobAttempt(key, 2)),
        failure_kind=FailureKind.TRANSPORT,
        canonical_exists=False,
    )
    assert not exhausted.eligible and exhausted.next_attempt_no is None


def test_job_scope_identity_matches_reader_critic_and_reviewer_cardinality() -> None:
    reader = LogicalJobKey("inv-1", JobType.PAPER_READ, "paper-1")
    critic = LogicalJobKey("inv-1", JobType.PAPER_CRITIQUE, "paper-1")
    reviewer = LogicalJobKey("inv-1", JobType.CORPUS_REVIEW, None)
    assert reader != critic
    assert reviewer.paper_id is None

    with pytest.raises(GuardViolation, match="paper_id=None"):
        LogicalJobKey("inv-1", JobType.CORPUS_REVIEW, "paper-1")
    with pytest.raises(GuardViolation, match="require paper_id"):
        LogicalJobKey("inv-1", JobType.PAPER_READ, None)

    ensure_single_logical_job_scope((reader, critic, reviewer))
    with pytest.raises(GuardViolation, match="more than one logical job"):
        ensure_single_logical_job_scope((reader, reader))


def test_duplicate_physical_attempt_identity_is_rejected() -> None:
    key = LogicalJobKey("inv-1", JobType.PAPER_READ, "paper-1")
    duplicate = (JobAttempt(key, 1), JobAttempt(key, 1))
    with pytest.raises(GuardViolation, match="duplicate physical attempt identity"):
        next_attempt(
            key=key,
            prior_attempts=duplicate,
            failure_kind=FailureKind.TRANSPORT,
            canonical_exists=False,
        )


@pytest.mark.parametrize(
    "failure_kind",
    [
        FailureKind.SEMANTIC_OBJECTION,
        FailureKind.UNSUPPORTED,
        FailureKind.OVERCLAIMED,
        FailureKind.UNCERTAIN,
    ],
)
def test_valid_semantic_outcomes_are_not_retryable(failure_kind: FailureKind) -> None:
    key = LogicalJobKey("inv-1", JobType.PAPER_CRITIQUE, "paper-1")
    decision = next_attempt(
        key=key,
        prior_attempts=(JobAttempt(key, 1),),
        failure_kind=failure_kind,
        canonical_exists=False,
    )
    assert not decision.eligible


def test_canonical_artifact_prevents_any_additional_attempt() -> None:
    key = LogicalJobKey("inv-1", JobType.PAPER_READ, "paper-1")
    decision = next_attempt(
        key=key,
        prior_attempts=(JobAttempt(key, 1),),
        failure_kind=FailureKind.SCHEMA_VALIDATION,
        canonical_exists=True,
    )
    assert not decision.eligible


def test_reviewer_barrier_requires_all_papers_terminal_and_exact_accounting() -> None:
    states = {
        "paper-1": PaperState.COMPLETE,
        "paper-2": PaperState.UNRESOLVED,
        "paper-3": PaperState.FAILED,
    }
    next_state = WorkflowService.prepare_reviewer(
        InvestigationState.ANALYZING,
        included_paper_states=states,
        accounting=Accounting(expected=3, complete=1, unresolved=1, failed=1),
    )
    assert next_state is InvestigationState.REVIEWING

    with pytest.raises(GuardViolation, match="all included papers terminal"):
        WorkflowService.prepare_reviewer(
            InvestigationState.ANALYZING,
            included_paper_states={"paper-1": PaperState.CRITIC_RUNNING},
            accounting=Accounting(expected=1, complete=0, unresolved=0, failed=1),
        )
    with pytest.raises(GuardViolation, match="accounting mismatch"):
        WorkflowService.prepare_reviewer(
            InvestigationState.ANALYZING,
            included_paper_states=states,
            accounting=Accounting(expected=3, complete=2, unresolved=0, failed=1),
        )


def test_blocked_review_does_not_invent_an_investigation_state() -> None:
    decision = WorkflowService.accept_review(
        InvestigationState.REVIEWING, report_status=ReviewReportStatus.BLOCKED
    )
    assert decision.blocked
    assert decision.next_state is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_concurrent_papers": 0, "max_concurrent_fetches": 1, "max_concurrent_agents": 1},
        {"max_concurrent_papers": 1, "max_concurrent_fetches": -1, "max_concurrent_agents": 1},
        {"max_concurrent_papers": 1, "max_concurrent_fetches": 1, "max_concurrent_agents": True},
    ],
)
def test_concurrency_limits_are_explicit_positive_integers(kwargs) -> None:
    with pytest.raises(GuardViolation, match="positive integer"):
        ConcurrencyConfig(**kwargs)


def test_concurrency_limits_are_independent() -> None:
    config = ConcurrencyConfig(
        max_concurrent_papers=3,
        max_concurrent_fetches=2,
        max_concurrent_agents=1,
    )
    assert config.max_concurrent_fetches == 2
    assert config.max_concurrent_agents == 1


def test_recovery_marks_orphaned_start_interrupted_with_bounded_retry() -> None:
    actions = recovery_actions(
        RecoverySnapshot(
            attempt_no=1,
            start_event_exists=True,
            outcome_exists=False,
            validation_passed=False,
            canonical_artifact_exists=False,
            completion_event_exists=False,
            sqlite_row_exists=True,
            hashes_verified=False,
        )
    )
    assert actions == (RecoveryAction.MARK_INTERRUPTED_RETRY_ELIGIBLE,)


def test_recovery_reconciles_verified_canonical_without_completion() -> None:
    actions = recovery_actions(
        RecoverySnapshot(
            attempt_no=1,
            start_event_exists=True,
            outcome_exists=False,
            validation_passed=True,
            canonical_artifact_exists=True,
            completion_event_exists=False,
            sqlite_row_exists=False,
            hashes_verified=True,
        )
    )
    assert actions == (RecoveryAction.APPEND_RECONCILED_EVENT,)


def test_recovery_reindexes_trace_completion_missing_from_sqlite() -> None:
    actions = recovery_actions(
        RecoverySnapshot(
            attempt_no=1,
            start_event_exists=True,
            outcome_exists=True,
            validation_passed=True,
            canonical_artifact_exists=True,
            completion_event_exists=True,
            sqlite_row_exists=False,
            hashes_verified=True,
        )
    )
    assert actions == (RecoveryAction.REINDEX_SQLITE,)


def test_recovery_rejects_sqlite_row_without_backing_evidence() -> None:
    actions = recovery_actions(
        RecoverySnapshot(
            attempt_no=1,
            start_event_exists=False,
            outcome_exists=False,
            validation_passed=False,
            canonical_artifact_exists=False,
            completion_event_exists=False,
            sqlite_row_exists=True,
            hashes_verified=False,
            sqlite_support_artifact_exists=False,
            sqlite_support_trace_exists=False,
        )
    )
    assert actions == (RecoveryAction.INTEGRITY_ERROR,)
