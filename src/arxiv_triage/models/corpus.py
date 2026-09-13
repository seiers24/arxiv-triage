"""Frozen corpus membership contracts."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from .base import (
    ContractModel,
    Identifier,
    NonNegativeInt,
    PositiveInt,
    Sha256,
    Text,
    UtcTimestamp,
    require_self_hash,
)


class CorpusEntry(ContractModel):
    ordinal: PositiveInt
    paper_id: Identifier
    membership_status: Literal["included", "excluded", "membership_unresolved"]
    discovery_refs: list[Identifier] = Field(min_length=1)
    inclusion_reason: Text | None
    exclusion_reason: Text | None
    # The specification says the initial manifest is immutable and terminal
    # states are stored in separate paper-state artifacts.
    terminal_state: None

    @model_validator(mode="after")
    def membership_reason_is_consistent(self) -> Self:
        if len(self.discovery_refs) != len(set(self.discovery_refs)):
            raise ValueError("discovery_refs must be unique")
        if self.membership_status == "included":
            if self.inclusion_reason is None or self.exclusion_reason is not None:
                raise ValueError("included entries require only an inclusion_reason")
        elif self.membership_status == "excluded":
            if self.exclusion_reason is None or self.inclusion_reason is not None:
                raise ValueError("excluded entries require only an exclusion_reason")
        elif self.inclusion_reason is not None or self.exclusion_reason is not None:
            raise ValueError(
                "membership-unresolved entries cannot use inclusion or exclusion reasons"
            )
        return self


class CorpusCounts(ContractModel):
    discovered: NonNegativeInt
    included: NonNegativeInt
    excluded: NonNegativeInt
    membership_unresolved: NonNegativeInt


class CorpusManifest(ContractModel):
    schema_version: Literal["2.0"]
    investigation_id: Identifier
    search_plan_hash: Sha256
    frozen_at: UtcTimestamp
    entries: list[CorpusEntry]
    counts: CorpusCounts
    corpus_hash: Sha256

    @model_validator(mode="after")
    def entries_are_unique_and_counted(self) -> Self:
        ordinals = [entry.ordinal for entry in self.entries]
        paper_ids = [entry.paper_id for entry in self.entries]
        if len(ordinals) != len(set(ordinals)):
            raise ValueError("corpus ordinals must be unique")
        if len(paper_ids) != len(set(paper_ids)):
            raise ValueError("corpus paper_id values must be unique")
        if self.counts.discovered != len(self.entries):
            raise ValueError("counts.discovered must equal the number of entries")
        included = sum(entry.membership_status == "included" for entry in self.entries)
        excluded = sum(entry.membership_status == "excluded" for entry in self.entries)
        membership_unresolved = sum(
            entry.membership_status == "membership_unresolved" for entry in self.entries
        )
        if self.counts.included != included:
            raise ValueError("counts.included does not match corpus entries")
        if self.counts.excluded != excluded:
            raise ValueError("counts.excluded does not match corpus entries")
        if self.counts.membership_unresolved != membership_unresolved:
            raise ValueError(
                "counts.membership_unresolved does not match corpus entries"
            )
        require_self_hash(self, "corpus_hash")
        return self
