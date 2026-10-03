"""Workshop-component contracts layered on the shared investigation core."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, StrictBool, StrictFloat, StrictInt, model_validator

from arxiv_triage.models import (
    ContractModel,
    Identifier,
    NonNegativeInt,
    PositiveInt,
    RepositoryRelativePath,
    Sha256,
    Score,
    Text,
    UtcTimestamp,
    require_self_hash,
)


class WorkshopTrack(ContractModel):
    track_id: Identifier
    name: Text
    proceedings_included: StrictBool


class WorkshopSpec(ContractModel):
    schema_version: Literal["2.0"]
    workshop_id: Identifier
    name: Text
    ordinal: PositiveInt
    venue: Text
    year: StrictInt
    dates: list[Text] = Field(min_length=1)
    authoritative_url: Text
    requested_population: Literal["accepted"]
    tracks: list[WorkshopTrack] = Field(min_length=1)
    source_precedence: list[Text] = Field(min_length=1)
    spec_hash: Sha256

    @model_validator(mode="after")
    def identifiers_and_hash_are_valid(self) -> Self:
        track_ids = [track.track_id for track in self.tracks]
        if len(track_ids) != len(set(track_ids)):
            raise ValueError("workshop track IDs must be unique")
        if self.year < 2000:
            raise ValueError("workshop year must be 2000 or later")
        require_self_hash(self, "spec_hash")
        return self


class WorkshopSourceSpan(ContractModel):
    response_sha256: Sha256
    start_char: NonNegativeInt
    end_char: PositiveInt
    quote: Text

    @model_validator(mode="after")
    def range_is_nonempty(self) -> Self:
        if self.end_char <= self.start_char:
            raise ValueError("workshop source span must be non-empty")
        return self

    def validate_against(self, source_text: str, source_hash: str) -> None:
        if self.response_sha256 != source_hash:
            raise ValueError("workshop source span hash does not match response")
        if self.end_char > len(source_text):
            raise ValueError("workshop source span exceeds response text")
        if source_text[self.start_char : self.end_char] != self.quote:
            raise ValueError("workshop source span quote does not reconstruct")


class WorkshopEntry(ContractModel):
    schema_version: Literal["2.0"]
    entry_id: Identifier
    ordinal: PositiveInt
    displayed_title: Text
    authors: list[Text] = Field(min_length=1)
    track_id: Identifier
    poster_number: PositiveInt
    acceptance_status: Literal["accepted"]
    listing_span: WorkshopSourceSpan
    paper_id: Identifier | None
    resolution_method: Text | None
    resolution_confidence: Literal["exact", "probable"] | None
    resolution_status: Literal[
        "unresolved", "resolved_exact", "resolved_probable", "ambiguous", "not_found"
    ]
    human_review_reason: Text | None
    entry_hash: Sha256

    @model_validator(mode="after")
    def resolution_and_hash_are_valid(self) -> Self:
        if self.resolution_status == "resolved_exact":
            if (
                self.paper_id is None
                or self.resolution_method is None
                or self.resolution_confidence != "exact"
                or self.human_review_reason is not None
            ):
                raise ValueError("resolved-exact entry fields are inconsistent")
        elif self.resolution_status == "resolved_probable":
            if (
                self.paper_id is None
                or self.resolution_method is None
                or self.resolution_confidence != "probable"
                or self.human_review_reason is None
            ):
                raise ValueError("resolved-probable entry requires human review")
        elif self.paper_id is not None or self.resolution_confidence is not None:
            raise ValueError("unresolved, ambiguous, and not-found entries cannot bind a paper")
        require_self_hash(self, "entry_hash")
        return self


class WorkshopAccounting(ContractModel):
    declared: NonNegativeInt
    extracted: NonNegativeInt
    resolved: NonNegativeInt
    identity_unresolved: NonNegativeInt

    @model_validator(mode="after")
    def counts_are_bounded(self) -> Self:
        if self.extracted > self.declared:
            raise ValueError("workshop extracted count cannot exceed declared count")
        if self.resolved + self.identity_unresolved != self.extracted:
            raise ValueError("workshop identity accounting must equal extracted entries")
        return self


class WorkshopCorpusManifest(ContractModel):
    schema_version: Literal["2.0"]
    workshop_spec_hash: Sha256
    authoritative_url: Text
    request_sha256: Sha256
    response_path: RepositoryRelativePath
    response_sha256: Sha256
    retrieved_at: UtcTimestamp
    entries: list[WorkshopEntry]
    excluded_nonpaper_items: list[Text]
    warnings: list[Text]
    accounting: WorkshopAccounting
    completeness_status: Literal["complete", "incomplete"]
    manifest_hash: Sha256

    @model_validator(mode="after")
    def entries_and_hash_are_valid(self) -> Self:
        ordinals = [entry.ordinal for entry in self.entries]
        entry_ids = [entry.entry_id for entry in self.entries]
        entry_hashes = [entry.entry_hash for entry in self.entries]
        if len(ordinals) != len(set(ordinals)) or sorted(ordinals) != list(
            range(1, len(self.entries) + 1)
        ):
            raise ValueError("workshop entry ordinals must be contiguous and unique")
        if len(entry_ids) != len(set(entry_ids)):
            raise ValueError("workshop entry IDs must be unique")
        if len(entry_hashes) != len(set(entry_hashes)):
            raise ValueError("workshop entry hashes must be unique")
        if self.accounting.extracted != len(self.entries):
            raise ValueError("workshop extracted count must equal entries")
        complete = self.accounting.extracted == self.accounting.declared
        if complete != (self.completeness_status == "complete"):
            raise ValueError("workshop completeness status does not match counts")
        if any(entry.listing_span.response_sha256 != self.response_sha256 for entry in self.entries):
            raise ValueError("workshop entry span hash does not match manifest response")
        require_self_hash(self, "manifest_hash")
        return self


class WorkshopRankingPolicy(ContractModel):
    """Deterministic top-tier rule layered on an objective profile."""

    schema_version: Literal["2.0"]
    objective_profile_hash: Sha256
    top_tier_min_total: StrictInt | StrictFloat
    criterion_minimums: dict[str, Score]
    exclude_uncertain: StrictBool
    policy_hash: Sha256

    @model_validator(mode="after")
    def bounds_and_hash_are_valid(self) -> Self:
        if isinstance(self.top_tier_min_total, bool) or not (
            0 <= self.top_tier_min_total <= 5
        ):
            raise ValueError("top-tier total threshold must be between 0 and 5")
        if not self.criterion_minimums:
            raise ValueError("top-tier criterion minimums must not be empty")
        require_self_hash(self, "policy_hash")
        return self


__all__ = [
    "WorkshopAccounting",
    "WorkshopCorpusManifest",
    "WorkshopEntry",
    "WorkshopSourceSpan",
    "WorkshopSpec",
    "WorkshopTrack",
    "WorkshopRankingPolicy",
]
