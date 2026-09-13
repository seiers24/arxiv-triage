"""Universal investigation, objective, and search-plan contracts."""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import Field, StrictBool, StrictFloat, StrictInt, model_validator

from .base import ContractModel, JsonObject, Rfc3339, Sha256, Text


class InvestigationSpec(ContractModel):
    schema_version: Literal["2.0"]
    investigation_id: Text
    kind: Text
    question: Text
    scope: JsonObject
    requested_outputs: list[Text]
    uncertainty_policy: Text
    created_at: Rfc3339
    spec_hash: Sha256


class ObjectiveCriterion(ContractModel):
    criterion_id: Text
    definition: Text
    score_type: Literal["integer_0_5"]
    weight: StrictInt | StrictFloat
    gate: StrictBool
    anchors: dict[str, Text]

    @model_validator(mode="after")
    def integer_score_anchors_are_valid(self) -> Self:
        if self.weight < 0:
            raise ValueError("criterion weight must be non-negative")
        if not self.anchors:
            raise ValueError("criterion anchors must not be empty")
        for raw_score in self.anchors:
            if raw_score not in {"0", "1", "2", "3", "4", "5"}:
                raise ValueError("integer_0_5 anchor keys must be 0 through 5")
        return self


class ObjectiveProfile(ContractModel):
    schema_version: Literal["2.0"]
    profile_id: Text
    component: Text
    origin: Literal["user_authored", "ai_drafted", "template_derived"]
    criteria: list[ObjectiveCriterion] = Field(min_length=1)
    human_review_triggers: list[Text]
    profile_hash: Sha256

    @model_validator(mode="after")
    def criterion_ids_are_unique(self) -> Self:
        ids = [criterion.criterion_id for criterion in self.criteria]
        if len(ids) != len(set(ids)):
            raise ValueError("criterion_id values must be unique")
        return self


class SearchPlan(ContractModel):
    schema_version: Literal["2.0"]
    search_plan_id: Text
    component: Text
    providers: list[JsonObject]
    inclusion_rules: list[Any]
    exclusion_rules: list[Any]
    completion_rule: JsonObject
    budget: JsonObject
    search_plan_hash: Sha256
