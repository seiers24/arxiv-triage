"""Immutable terminal-state record for one included paper."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import model_validator

from .base import (
    ContractModel,
    Identifier,
    Sha256,
    Text,
    UtcTimestamp,
    require_self_hash,
)


class PaperStateRecord(ContractModel):
    """Persist the terminal analysis disposition outside the frozen corpus."""

    schema_version: Literal["2.0"]
    investigation_id: Identifier
    paper_id: Identifier
    terminal_state: Literal["complete", "analysis_unresolved", "failed"]
    source_document_id: Identifier | None
    reader_run_id: Identifier | None
    critic_run_id: Identifier | None
    error: Text | None
    completed_at: UtcTimestamp
    state_hash: Sha256

    @model_validator(mode="after")
    def terminal_fields_are_consistent(self) -> Self:
        if self.terminal_state == "failed":
            if self.error is None:
                raise ValueError("a failed paper state requires an error")
            if self.critic_run_id is not None:
                raise ValueError("a failed paper state cannot reference a canonical critic")
        else:
            if any(
                value is None
                for value in (
                    self.source_document_id,
                    self.reader_run_id,
                    self.critic_run_id,
                )
            ):
                raise ValueError(
                    "complete and analysis-unresolved states require source, reader, and critic IDs"
                )
            if self.error is not None:
                raise ValueError("a non-failed paper state cannot contain an error")
        require_self_hash(self, "state_hash")
        return self


__all__ = ["PaperStateRecord"]
