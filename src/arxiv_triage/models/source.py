"""Frozen source-packet contracts and exact quote reconstruction."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from .base import ContractModel, NonNegativeInt, Rfc3339, Sha256, Text, sha256_bytes


class SourceSection(ContractModel):
    section_id: Text
    heading: Text
    start_char: NonNegativeInt
    end_char: NonNegativeInt

    @model_validator(mode="after")
    def nonempty_range(self) -> Self:
        if self.end_char <= self.start_char:
            raise ValueError("section end_char must be greater than start_char")
        return self


class SourcePacket(ContractModel):
    schema_version: Literal["2.0"]
    source_document_id: Text
    paper_id: Text
    format: Text
    retrieval_method: Text
    source_url: Text
    retrieved_at: Rfc3339
    original_path: Text
    original_sha256: Sha256
    normalized_path: Text
    normalized_sha256: Sha256
    sections: list[SourceSection]
    warnings: list[Text]
    packet_hash: Sha256

    @model_validator(mode="after")
    def sections_are_unique_and_ordered(self) -> Self:
        ids = [section.section_id for section in self.sections]
        if len(ids) != len(set(ids)):
            raise ValueError("source section_id values must be unique")
        for previous, current in zip(self.sections, self.sections[1:], strict=False):
            if current.start_char < previous.end_char:
                raise ValueError("source sections must be ordered and non-overlapping")
        return self

    def section(self, section_id: str) -> SourceSection:
        """Return the addressed section or reject an unknown locator."""

        for section in self.sections:
            if section.section_id == section_id:
                return section
        raise ValueError(f"unknown source section_id: {section_id}")

    def validate_normalized_text(self, normalized_text: str) -> None:
        """Verify normalized bytes and all section ranges against the packet."""

        if sha256_bytes(normalized_text.encode("utf-8")) != self.normalized_sha256:
            raise ValueError("normalized source text hash does not match the packet")
        if any(section.end_char > len(normalized_text) for section in self.sections):
            raise ValueError("source section range exceeds normalized source text")

    def validate_locator(
        self,
        *,
        document_sha256: str,
        section_id: str,
        start_char: int,
        end_char: int,
        quote: str,
        normalized_text: str,
    ) -> None:
        """Reconstruct and validate an exact source quote.

        Offsets address Python string code points, as required by the v2
        specification.
        """

        self.validate_normalized_text(normalized_text)
        if document_sha256 != self.normalized_sha256:
            raise ValueError("source locator document hash does not match the packet")
        if start_char < 0 or end_char <= start_char or end_char > len(normalized_text):
            raise ValueError("source locator character range is invalid")
        section = self.section(section_id)
        if start_char < section.start_char or end_char > section.end_char:
            raise ValueError("source locator range falls outside its section")
        if normalized_text[start_char:end_char] != quote:
            raise ValueError("source locator quote does not match normalized source text")
