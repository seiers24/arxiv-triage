"""The fully specified portion of corpus-review output contracts."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import StrictBool, model_validator

from .base import ContractModel, NonNegativeInt, Text


class CorpusAccounting(ContractModel):
    expected: NonNegativeInt
    complete: NonNegativeInt
    unresolved: NonNegativeInt
    failed: NonNegativeInt
    accounting_valid: StrictBool

    @model_validator(mode="after")
    def validity_matches_counts(self) -> Self:
        counts_match = self.expected == self.complete + self.unresolved + self.failed
        if self.accounting_valid != counts_match:
            raise ValueError("accounting_valid must agree with the corpus totals")
        return self


class ReviewFinding(ContractModel):
    finding_id: Text
    text: Text
    evidence_refs: list[Text]
    provenance: Literal["reviewer_inferred"]
    uncertain: StrictBool


__all__ = ["CorpusAccounting", "ReviewFinding"]
