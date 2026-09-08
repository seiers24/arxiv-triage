"""Validate the Pydantic JSON contracts defined in ``docs/schema.md``.

The JSON artifacts are the complete evidence records. SQLite is a partial,
rebuildable projection of validated instances of these models.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Annotated, Literal, Mapping, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StringConstraints,
    model_validator,
)


SCHEMA_VERSION = "1.0"


def _nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("must contain a non-whitespace character")
    return value


def _rfc3339(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("must be an RFC 3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("must include a timezone")
    return value


def _utc_rfc3339(value: str) -> str:
    _rfc3339(value)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("must be a UTC timestamp")
    return value


ShortText = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=200),
    AfterValidator(_nonblank),
]
MediumText = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=400),
    AfterValidator(_nonblank),
]
ReasonText = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=600),
    AfterValidator(_nonblank),
]
LongText = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=1_000),
    AfterValidator(_nonblank),
]
AbstractText = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=20_000),
    AfterValidator(_nonblank),
]
Identifier = Annotated[
    str,
    StringConstraints(strict=True, min_length=1),
    AfterValidator(_nonblank),
]
Sha256 = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$"),
]
ObjectiveId = Annotated[
    str,
    StringConstraints(
        strict=True,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    ),
]
CategoryId = Annotated[
    str,
    StringConstraints(
        strict=True,
        pattern=r"^[a-z0-9]+(?:_[a-z0-9]+)*$",
    ),
]
ArxivId = Annotated[
    str,
    StringConstraints(
        strict=True,
        pattern=(
            r"^(?:\d{4}\.\d{4,5}|"
            r"[a-z][a-z-]*(?:\.[A-Za-z-]+)?/\d{7})v[1-9]\d*$"
        ),
    ),
]
Rfc3339 = Annotated[str, StringConstraints(strict=True), AfterValidator(_rfc3339)]
UtcRfc3339 = Annotated[
    str,
    StringConstraints(strict=True),
    AfterValidator(_utc_rfc3339),
]
Score = Annotated[StrictInt, Field(ge=0, le=5)]
Weight = Annotated[StrictInt, Field(ge=0, le=100)]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
NonNegativeNumber = Annotated[StrictInt | StrictFloat, Field(ge=0)]

EvidenceType = Literal["simulation", "real_hardware", "theory", "none_stated"]
Provenance = Literal["preprint", "peer_reviewed", "blog_or_docs", "inferred"]
ReaderProvenance = Literal["preprint", "peer_reviewed", "inferred"]
ClaimStatus = Literal[
    "unverified", "supported", "unsupported", "overclaimed", "unresolved"
]
CriticVerdictStatus = Literal["supported", "unsupported", "overclaimed"]
WorkflowState = Literal["complete", "unresolved", "failed"]
Role = Literal["reader", "critic"]


class ContractModel(BaseModel):
    """Base configuration shared by every contract object."""

    model_config = ConfigDict(extra="forbid", strict=True)


def canonical_json(value: BaseModel | Mapping[str, object]) -> str:
    """Serialize a model or mapping using the contract's canonical JSON form."""
    if isinstance(value, BaseModel):
        payload = value.model_dump(mode="json")
    else:
        payload = dict(value)
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def sha256_json(value: BaseModel | Mapping[str, object]) -> str:
    """Return the SHA-256 of canonical JSON for ``value``."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def normalize_span(value: str) -> str:
    """Apply the schema's source-span-only whitespace normalization."""
    return re.sub(r"\s+", " ", value, flags=re.UNICODE).strip()


class ObjectiveScope(ContractModel):
    include: list[MediumText] = Field(min_length=1)
    exclude: list[MediumText]

    @model_validator(mode="after")
    def unique_items(self) -> Self:
        if len(set(self.include)) != len(self.include):
            raise ValueError("scope.include entries must be unique")
        if len(set(self.exclude)) != len(self.exclude):
            raise ValueError("scope.exclude entries must be unique")
        return self


class RelevanceCategory(ContractModel):
    id: CategoryId
    description: MediumText

    @model_validator(mode="after")
    def reserved_id(self) -> Self:
        if self.id == "not_relevant":
            raise ValueError("not_relevant is reserved; use null for an irrelevant paper")
        return self


class RankingWeights(ContractModel):
    relevance_weight: Weight
    technical_importance_weight: Weight
    extendability_weight: Weight

    @model_validator(mode="after")
    def at_least_one_nonzero(self) -> Self:
        if not any(
            (
                self.relevance_weight,
                self.technical_importance_weight,
                self.extendability_weight,
            )
        ):
            raise ValueError("at least one ranking weight must be greater than zero")
        return self


class ObjectiveProfile(ContractModel):
    schema_version: Literal["1.0"]
    objective_id: ObjectiveId
    title: ShortText
    research_question: LongText
    scope: ObjectiveScope
    relevance_categories: list[RelevanceCategory] = Field(min_length=1, max_length=20)
    ranking: RankingWeights
    extension_priorities: list[MediumText] = Field(max_length=20)

    @model_validator(mode="after")
    def unique_categories_and_priorities(self) -> Self:
        category_ids = [category.id for category in self.relevance_categories]
        if len(set(category_ids)) != len(category_ids):
            raise ValueError("relevance category IDs must be unique")
        if len(set(self.extension_priorities)) != len(self.extension_priorities):
            raise ValueError("extension priorities must be unique")
        return self

    @property
    def objective_hash(self) -> str:
        return sha256_json(self)


class FrozenPaper(ContractModel):
    schema_version: Literal["1.0"]
    arxiv_id: ArxivId
    title: LongText
    abstract: AbstractText
    authors: list[Identifier] = Field(min_length=1)
    published: Rfc3339
    updated: Rfc3339 | None
    journal_reference: Identifier | None
    doi: Identifier | None
    input_hash: Sha256

    @model_validator(mode="after")
    def hash_matches_contents(self) -> Self:
        payload = self.model_dump(mode="json", exclude={"input_hash"})
        expected = sha256_json(payload)
        if self.input_hash != expected:
            raise ValueError("input_hash does not match the canonical frozen paper")
        return self


class ReaderDispatch(ContractModel):
    schema_version: Literal["1.0"]
    paper: FrozenPaper
    objective: ObjectiveProfile
    objective_hash: Sha256

    @model_validator(mode="after")
    def hash_matches_objective(self) -> Self:
        if self.objective_hash != self.objective.objective_hash:
            raise ValueError("objective_hash does not match the objective profile")
        return self

    def validate_record(
        self, value: ReaderRecord | Mapping[str, object]
    ) -> ReaderRecord:
        """Validate a reader record against this exact paper and objective."""
        record = (
            value
            if isinstance(value, ReaderRecord)
            else ReaderRecord.model_validate(value)
        )
        if record.arxiv_id != self.paper.arxiv_id:
            raise ValueError("reader arxiv_id does not match the frozen paper")
        if record.input_hash != self.paper.input_hash:
            raise ValueError("reader input_hash does not match the frozen paper")
        if record.objective_id != self.objective.objective_id:
            raise ValueError("reader objective_id does not match the objective")
        if record.objective_hash != self.objective_hash:
            raise ValueError("reader objective_hash does not match the objective")

        categories = {category.id for category in self.objective.relevance_categories}
        if record.relevance_category is not None and record.relevance_category not in categories:
            raise ValueError("reader relevance_category is not declared by the objective")

        normalized_abstract = normalize_span(self.paper.abstract)
        for index, claim in enumerate(record.claims):
            if claim.source_span is not None:
                if normalize_span(claim.source_span) not in normalized_abstract:
                    raise ValueError(
                        f"claim {index} source_span is not in the frozen abstract"
                    )
            if claim.provenance == "peer_reviewed" and self.paper.journal_reference is None:
                raise ValueError(
                    f"claim {index} cannot be peer_reviewed without a journal reference"
                )
        return record


class Claim(ContractModel):
    text: LongText
    source_span: LongText | None
    evidence_type: EvidenceType
    provenance: ReaderProvenance
    status: Literal["unverified"]

    @model_validator(mode="after")
    def source_and_provenance_agree(self) -> Self:
        if self.source_span is None:
            if self.provenance != "inferred":
                raise ValueError("a null source_span requires inferred provenance")
            if self.evidence_type != "none_stated":
                raise ValueError("a null source_span requires none_stated evidence")
        elif self.provenance not in ("preprint", "peer_reviewed"):
            raise ValueError("a non-null source_span requires paper provenance")
        return self


class ExtensionProposal(ContractModel):
    provenance: Literal["inferred"]
    hypothesis: ReasonText
    smallest_useful_experiment: LongText
    comparison_baseline: ReasonText
    success_metric: ReasonText


class ReaderRecord(ContractModel):
    schema_version: Literal["1.0"]
    role: Literal["reader"]
    arxiv_id: ArxivId
    input_hash: Sha256
    objective_id: ObjectiveId
    objective_hash: Sha256
    problem: ReasonText
    method: ReasonText
    technical_importance: Score
    objective_relevance: Score
    extendable: StrictBool
    reason: ReasonText
    relevance_category: CategoryId | None
    relevance_claim_indices: list[StrictInt]
    relevance_assumptions: list[MediumText]
    claims: list[Claim] = Field(min_length=1, max_length=20)
    extension_proposal: ExtensionProposal | None

    @model_validator(mode="after")
    def relevance_and_extension_are_consistent(self) -> Self:
        indices = self.relevance_claim_indices
        if len(set(indices)) != len(indices):
            raise ValueError("relevance_claim_indices must be unique")
        if any(index < 0 or index >= len(self.claims) for index in indices):
            raise ValueError("relevance_claim_indices contains an out-of-bounds index")
        if any(self.claims[index].provenance == "inferred" for index in indices):
            raise ValueError("relevance cannot link to an inferred claim")

        if self.objective_relevance == 0:
            if self.relevance_category is not None or indices:
                raise ValueError(
                    "zero objective_relevance requires a null category and no claim links"
                )
        elif self.relevance_category is None or not indices:
            raise ValueError(
                "positive objective_relevance requires a category and claim link"
            )

        if self.extendable != (self.extension_proposal is not None):
            raise ValueError("extendable must agree with extension_proposal presence")
        return self


class CriticDispatch(ContractModel):
    schema_version: Literal["1.0"]
    paper: FrozenPaper
    objective: ObjectiveProfile
    objective_hash: Sha256
    reader_record: ReaderRecord
    reader_run_id: Identifier

    @model_validator(mode="after")
    def inputs_are_compatible(self) -> Self:
        dispatch = ReaderDispatch(
            schema_version=self.schema_version,
            paper=self.paper,
            objective=self.objective,
            objective_hash=self.objective_hash,
        )
        dispatch.validate_record(self.reader_record)
        return self

    def validate_record(
        self, value: CriticRecord | Mapping[str, object]
    ) -> CriticRecord:
        """Validate a critic record against this reader attempt and its inputs."""
        record = (
            value
            if isinstance(value, CriticRecord)
            else CriticRecord.model_validate(value)
        )
        if record.arxiv_id != self.paper.arxiv_id:
            raise ValueError("critic arxiv_id does not match the frozen paper")
        if record.objective_id != self.objective.objective_id:
            raise ValueError("critic objective_id does not match the objective")
        if record.objective_hash != self.objective_hash:
            raise ValueError("critic objective_hash does not match the objective")
        if record.reader_run_id != self.reader_run_id:
            raise ValueError("critic reader_run_id does not match its input")

        expected = set(range(len(self.reader_record.claims)))
        actual = {verdict.claim_index for verdict in record.verdicts}
        if actual != expected:
            raise ValueError("critic must return exactly one verdict per reader claim")

        verdicts = {verdict.claim_index: verdict for verdict in record.verdicts}
        for index, claim in enumerate(self.reader_record.claims):
            if claim.source_span is None and verdicts[index].status == "supported":
                raise ValueError(f"claim {index} has no source span and cannot be supported")

        linked_rejection = any(
            verdicts[index].status in ("unsupported", "overclaimed")
            for index in self.reader_record.relevance_claim_indices
        )
        if linked_rejection and record.objective_relevance_assessment.justified:
            raise ValueError(
                "objective relevance cannot be justified when a linked claim is rejected"
            )
        return record


class ClaimVerdict(ContractModel):
    claim_index: NonNegativeInt
    status: CriticVerdictStatus
    reason: ReasonText


class ObjectiveRelevanceAssessment(ContractModel):
    justified: StrictBool
    reason: ReasonText


class CriticRecord(ContractModel):
    schema_version: Literal["1.0"]
    role: Literal["critic"]
    arxiv_id: ArxivId
    objective_id: ObjectiveId
    objective_hash: Sha256
    reader_run_id: Identifier
    verdicts: list[ClaimVerdict]
    objective_relevance_assessment: ObjectiveRelevanceAssessment

    @model_validator(mode="after")
    def verdict_indices_are_unique(self) -> Self:
        indices = [verdict.claim_index for verdict in self.verdicts]
        if len(set(indices)) != len(indices):
            raise ValueError("critic verdict claim indices must be unique")
        return self


class VerdictSummary(ContractModel):
    supported: NonNegativeInt
    unsupported: NonNegativeInt
    overclaimed: NonNegativeInt
    objective_relevance_justified: StrictBool

    @property
    def verdict_count(self) -> int:
        return self.supported + self.unsupported + self.overclaimed


def _repository_relative(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ValueError("must be a repository-relative POSIX path")
    return value


ArtifactPath = Annotated[
    str,
    StringConstraints(strict=True, min_length=1),
    AfterValidator(_nonblank),
    AfterValidator(_repository_relative),
]


class TraceEvent(ContractModel):
    schema_version: Literal["1.0"]
    agent_run_id: Identifier
    arxiv_id: ArxivId
    role: Role
    timestamp: UtcRfc3339
    model: Identifier
    agent_hash: Sha256
    input_hash: Sha256
    objective_id: ObjectiveId
    objective_hash: Sha256
    artifact_path: ArtifactPath | None
    artifact_hash: Sha256 | None
    validation_pass: StrictBool
    retry_count: Annotated[StrictInt, Field(ge=0, le=1)]
    verdict_summary: VerdictSummary | None
    tokens_in: NonNegativeInt | None
    tokens_out: NonNegativeInt | None
    cost_usd: NonNegativeNumber | None
    error: Identifier | None

    @model_validator(mode="after")
    def outcome_fields_are_consistent(self) -> Self:
        if self.artifact_path is None:
            if self.artifact_hash is not None:
                raise ValueError("artifact_hash must be null when artifact_path is null")
            if self.validation_pass:
                raise ValueError("validation_pass cannot be true without an artifact")
        elif self.artifact_hash is None:
            raise ValueError("artifact_hash is required when artifact_path is present")

        if self.validation_pass:
            if self.error is not None:
                raise ValueError("a valid attempt cannot contain an error")
        elif self.error is None:
            raise ValueError("an invalid or failed attempt must contain an error")

        if self.role == "reader" and self.verdict_summary is not None:
            raise ValueError("reader trace events cannot contain a verdict summary")
        if self.role == "critic":
            if self.validation_pass and self.verdict_summary is None:
                raise ValueError("a valid critic event requires a verdict summary")
            if not self.validation_pass and self.verdict_summary is not None:
                raise ValueError("an invalid critic event cannot contain a verdict summary")
        return self
