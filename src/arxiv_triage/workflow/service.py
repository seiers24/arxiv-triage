"""Intent-level deterministic workflow façade.

This module returns state decisions only. Dispatch, validation, persistence, and
external I/O belong to their dedicated modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping

from .guards import (
    Accounting,
    GuardViolation,
    ensure_critic_dispatch_eligible,
    ensure_reader_dispatch_eligible,
    ensure_reviewer_barrier,
)
from .state import (
    InvestigationState,
    PaperState,
    transition_investigation,
    transition_paper,
)


class ReviewReportStatus(StrEnum):
    READY = "ready"
    READY_WITH_WARNINGS = "ready_with_warnings"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class ReviewAcceptanceDecision:
    """Result of accepting a valid reviewer artifact.

    The specification defines ``blocked`` as a review result but omits a matching
    investigation state. It is therefore represented without inventing a state
    transition; callers must surface the block for resolution.
    """

    next_state: InvestigationState | None
    blocked: bool


class WorkflowService:
    """Pure intent operations that enforce the documented transition guards."""

    @staticmethod
    def create_investigation(*, inputs_valid: bool) -> InvestigationState:
        if not inputs_valid:
            raise GuardViolation("all input schemas and hashes must be valid")
        return InvestigationState.INPUTS_VALIDATED

    @staticmethod
    def begin_discovery(
        current: InvestigationState, *, search_plan_present: bool
    ) -> InvestigationState:
        if not search_plan_present:
            raise GuardViolation("begin_discovery requires a search plan")
        return transition_investigation(current, InvestigationState.DISCOVERING)

    @staticmethod
    def freeze_corpus(
        current: InvestigationState, *, membership_valid: bool, counts_valid: bool
    ) -> InvestigationState:
        if not membership_valid or not counts_valid:
            raise GuardViolation("freeze_corpus requires valid membership and counts")
        return transition_investigation(current, InvestigationState.CORPUS_FROZEN)

    @staticmethod
    def begin_analysis(current: InvestigationState) -> InvestigationState:
        return transition_investigation(current, InvestigationState.ANALYZING)

    @staticmethod
    def prepare_reader(
        current: PaperState,
        *,
        source_files_verified: bool,
        source_hashes_verified: bool,
        canonical_reader_exists: bool,
    ) -> PaperState:
        ensure_reader_dispatch_eligible(
            paper_state=current,
            source_files_verified=source_files_verified,
            source_hashes_verified=source_hashes_verified,
            canonical_reader_exists=canonical_reader_exists,
        )
        return transition_paper(current, PaperState.READER_PENDING)

    @staticmethod
    def dispatch_reader(current: PaperState) -> PaperState:
        return transition_paper(current, PaperState.READER_RUNNING)

    @staticmethod
    def accept_reader(current: PaperState, *, cross_input_checks_pass: bool) -> PaperState:
        if not cross_input_checks_pass:
            raise GuardViolation("reader output and cross-input checks must pass")
        return transition_paper(current, PaperState.READER_VALIDATED)

    @staticmethod
    def prepare_critic(
        current: PaperState,
        *,
        source_hashes_verified: bool,
        canonical_reader_verified: bool,
        canonical_critic_exists: bool,
    ) -> PaperState:
        ensure_critic_dispatch_eligible(
            paper_state=current,
            source_hashes_verified=source_hashes_verified,
            canonical_reader_verified=canonical_reader_verified,
            canonical_critic_exists=canonical_critic_exists,
        )
        return transition_paper(current, PaperState.CRITIC_PENDING)

    @staticmethod
    def dispatch_critic(current: PaperState) -> PaperState:
        return transition_paper(current, PaperState.CRITIC_RUNNING)

    @staticmethod
    def accept_critic(
        current: PaperState, *, has_valid_objection_or_uncertainty: bool
    ) -> PaperState:
        target = (
            PaperState.UNRESOLVED
            if has_valid_objection_or_uncertainty
            else PaperState.COMPLETE
        )
        return transition_paper(current, target)

    @staticmethod
    def prepare_reviewer(
        current: InvestigationState,
        *,
        included_paper_states: Mapping[str, PaperState],
        accounting: Accounting,
    ) -> InvestigationState:
        ensure_reviewer_barrier(
            included_paper_states=included_paper_states,
            accounting=accounting,
        )
        return transition_investigation(current, InvestigationState.REVIEWING)

    @staticmethod
    def accept_review(
        current: InvestigationState, *, report_status: ReviewReportStatus
    ) -> ReviewAcceptanceDecision:
        if current is not InvestigationState.REVIEWING:
            # Use the shared transition exception and message for illegal states.
            transition_investigation(current, InvestigationState.RENDERING)
        if report_status is ReviewReportStatus.BLOCKED:
            return ReviewAcceptanceDecision(next_state=None, blocked=True)
        return ReviewAcceptanceDecision(
            next_state=transition_investigation(
                current, InvestigationState.RENDERING
            ),
            blocked=False,
        )

    @staticmethod
    def complete(
        current: InvestigationState,
        *,
        outputs_exist: bool,
        reviewer_blocked: bool,
        has_warnings: bool,
    ) -> InvestigationState:
        if not outputs_exist:
            raise GuardViolation("completion requires rendered outputs")
        if reviewer_blocked:
            raise GuardViolation("completion is forbidden while reviewer is blocked")
        target = (
            InvestigationState.COMPLETE_WITH_WARNINGS
            if has_warnings
            else InvestigationState.COMPLETE
        )
        return transition_investigation(current, target)
