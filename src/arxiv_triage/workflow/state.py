"""Closed workflow state machines from the core platform specification."""

from __future__ import annotations

from enum import StrEnum
from typing import TypeVar


class InvestigationState(StrEnum):
    DRAFT = "draft"
    INPUTS_VALIDATED = "inputs_validated"
    DISCOVERING = "discovering"
    CORPUS_FROZEN = "corpus_frozen"
    ANALYZING = "analyzing"
    REVIEWING = "reviewing"
    RENDERING = "rendering"
    COMPLETE = "complete"
    COMPLETE_WITH_WARNINGS = "complete_with_warnings"
    FAILED = "failed"


class PaperState(StrEnum):
    DISCOVERED = "discovered"
    RESOLVING_IDENTITY = "resolving_identity"
    FETCHING = "fetching"
    SOURCE_FROZEN = "source_frozen"
    READER_PENDING = "reader_pending"
    READER_RUNNING = "reader_running"
    READER_VALIDATED = "reader_validated"
    CRITIC_PENDING = "critic_pending"
    CRITIC_RUNNING = "critic_running"
    COMPLETE = "complete"
    UNRESOLVED = "unresolved"
    FAILED = "failed"


class AgentRunState(StrEnum):
    ALLOCATED = "allocated"
    RUNNING = "running"
    OUTPUT_RECEIVED = "output_received"
    VALIDATED = "validated"
    INVALID = "invalid"
    CANONICALIZED = "canonicalized"
    INDEXED = "indexed"
    FAILED = "failed"


INVESTIGATION_TERMINAL_STATES = frozenset(
    {
        InvestigationState.COMPLETE,
        InvestigationState.COMPLETE_WITH_WARNINGS,
        InvestigationState.FAILED,
    }
)
PAPER_TERMINAL_STATES = frozenset(
    {PaperState.COMPLETE, PaperState.UNRESOLVED, PaperState.FAILED}
)
AGENT_RUN_TERMINAL_STATES = frozenset({AgentRunState.INDEXED, AgentRunState.FAILED})


_INVESTIGATION_TRANSITIONS = {
    InvestigationState.DRAFT: {
        InvestigationState.INPUTS_VALIDATED,
        InvestigationState.FAILED,
    },
    InvestigationState.INPUTS_VALIDATED: {
        InvestigationState.DISCOVERING,
        InvestigationState.FAILED,
    },
    InvestigationState.DISCOVERING: {
        InvestigationState.CORPUS_FROZEN,
        InvestigationState.FAILED,
    },
    InvestigationState.CORPUS_FROZEN: {
        InvestigationState.ANALYZING,
        InvestigationState.FAILED,
    },
    InvestigationState.ANALYZING: {
        InvestigationState.REVIEWING,
        InvestigationState.FAILED,
    },
    InvestigationState.REVIEWING: {
        InvestigationState.RENDERING,
        InvestigationState.FAILED,
    },
    InvestigationState.RENDERING: {
        InvestigationState.COMPLETE,
        InvestigationState.COMPLETE_WITH_WARNINGS,
        InvestigationState.FAILED,
    },
}

_PAPER_TRANSITIONS = {
    PaperState.DISCOVERED: {PaperState.RESOLVING_IDENTITY},
    PaperState.RESOLVING_IDENTITY: {PaperState.FETCHING, PaperState.FAILED},
    PaperState.FETCHING: {PaperState.SOURCE_FROZEN, PaperState.FAILED},
    PaperState.SOURCE_FROZEN: {PaperState.READER_PENDING},
    PaperState.READER_PENDING: {PaperState.READER_RUNNING},
    PaperState.READER_RUNNING: {PaperState.READER_VALIDATED, PaperState.FAILED},
    PaperState.READER_VALIDATED: {PaperState.CRITIC_PENDING},
    PaperState.CRITIC_PENDING: {PaperState.CRITIC_RUNNING},
    PaperState.CRITIC_RUNNING: {
        PaperState.COMPLETE,
        PaperState.UNRESOLVED,
        PaperState.FAILED,
    },
}

_AGENT_RUN_TRANSITIONS = {
    AgentRunState.ALLOCATED: {AgentRunState.RUNNING},
    AgentRunState.RUNNING: {AgentRunState.OUTPUT_RECEIVED, AgentRunState.FAILED},
    AgentRunState.OUTPUT_RECEIVED: {
        AgentRunState.VALIDATED,
        AgentRunState.INVALID,
    },
    AgentRunState.INVALID: {AgentRunState.FAILED},
    AgentRunState.VALIDATED: {AgentRunState.CANONICALIZED},
    AgentRunState.CANONICALIZED: {AgentRunState.INDEXED},
}


class InvalidTransition(ValueError):
    """Raised when a caller requests an edge absent from a state diagram."""

    def __init__(self, machine: str, current: StrEnum, target: StrEnum) -> None:
        super().__init__(f"illegal {machine} transition: {current.value} -> {target.value}")
        self.machine = machine
        self.current = current
        self.target = target


StateT = TypeVar("StateT", bound=StrEnum)


def _can_transition(
    transitions: dict[StateT, set[StateT]], current: StateT, target: StateT
) -> bool:
    return target in transitions.get(current, set())


def _transition(
    machine: str,
    transitions: dict[StateT, set[StateT]],
    current: StateT,
    target: StateT,
) -> StateT:
    if not _can_transition(transitions, current, target):
        raise InvalidTransition(machine, current, target)
    return target


def can_transition_investigation(
    current: InvestigationState, target: InvestigationState
) -> bool:
    return _can_transition(_INVESTIGATION_TRANSITIONS, current, target)


def transition_investigation(
    current: InvestigationState, target: InvestigationState
) -> InvestigationState:
    return _transition("investigation", _INVESTIGATION_TRANSITIONS, current, target)


def can_transition_paper(current: PaperState, target: PaperState) -> bool:
    return _can_transition(_PAPER_TRANSITIONS, current, target)


def transition_paper(current: PaperState, target: PaperState) -> PaperState:
    return _transition("paper", _PAPER_TRANSITIONS, current, target)


def can_transition_agent_run(current: AgentRunState, target: AgentRunState) -> bool:
    return _can_transition(_AGENT_RUN_TRANSITIONS, current, target)


def transition_agent_run(current: AgentRunState, target: AgentRunState) -> AgentRunState:
    return _transition("agent run", _AGENT_RUN_TRANSITIONS, current, target)
