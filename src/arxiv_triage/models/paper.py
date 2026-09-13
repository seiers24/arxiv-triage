"""Stable paper identity contracts."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from .base import ContractModel, Rfc3339, Sha256, Text


class PaperIdentifier(ContractModel):
    scheme: Text
    value: Text
    url: Text


class PaperIdentity(ContractModel):
    schema_version: Literal["2.0"]
    paper_id: Text
    title: Text
    authors: list[Text] = Field(min_length=1)
    published: Rfc3339 | None
    identifiers: list[PaperIdentifier]
    identity_status: Text
    identity_hash: Sha256

    @model_validator(mode="after")
    def identifiers_are_unique(self) -> Self:
        keys = [(identifier.scheme, identifier.value) for identifier in self.identifiers]
        if len(keys) != len(set(keys)):
            raise ValueError("paper identifiers must be unique by scheme and value")
        return self
