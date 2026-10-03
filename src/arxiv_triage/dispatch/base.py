"""Provider-neutral interface for one physical worker invocation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class DispatchResult:
    raw_output: bytes
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: int | float | None = None


class WorkerDispatcher(Protocol):
    def dispatch(self, task: Any) -> DispatchResult:
        """Run exactly one physical invocation or raise a transport exception."""


__all__ = ["DispatchResult", "WorkerDispatcher"]
