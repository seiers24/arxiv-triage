"""Stable paper identity contracts."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from .base import ContractModel, Identifier, Sha256, Text, UtcTimestamp, require_self_hash


class PaperIdentifier(ContractModel):
    scheme: Literal["arxiv", "doi", "openreview", "url", "proceedings"]
    value: Text
    url: Text


class PaperIdentity(ContractModel):
    schema_version: Literal["2.0"]
    paper_id: Identifier
    title: Text
    authors: list[Text] = Field(min_length=1)
    published: UtcTimestamp | None
    identifiers: list[PaperIdentifier]
    identity_status: Literal[
        "unresolved", "resolved_exact", "resolved_probable", "ambiguous"
    ]
    identity_hash: Sha256

    @model_validator(mode="after")
    def identifiers_are_unique(self) -> Self:
        keys = [(identifier.scheme, identifier.value) for identifier in self.identifiers]
        if len(keys) != len(set(keys)):
            raise ValueError("paper identifiers must be unique by scheme and value")
        require_self_hash(self, "identity_hash")
        return self
