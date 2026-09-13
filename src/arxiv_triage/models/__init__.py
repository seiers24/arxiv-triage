"""Schema-version 2.0 core contracts."""

from .base import (
    SCHEMA_VERSION,
    ContractModel,
    JsonObject,
    NonNegativeInt,
    PositiveInt,
    Rfc3339,
    Score,
    Sha256,
    Text,
    canonical_json,
    sha256_bytes,
    sha256_json,
)
from .corpus import CorpusCounts, CorpusEntry, CorpusManifest
from .critic import (
    ClaimVerdict,
    CriticRecordDraft,
    CriticRubric,
    CriticTaskDraft,
    ObjectiveAssessment,
)
from .investigation import (
    InvestigationSpec,
    ObjectiveCriterion,
    ObjectiveProfile,
    SearchPlan,
)
from .paper import PaperIdentifier, PaperIdentity
from .reader import Claim, ReaderFocus, ReaderRecordDraft, ReaderTask, SourceLocator
from .reviewer import CorpusAccounting, ReviewFinding
from .source import SourcePacket, SourceSection

__all__ = [
    "SCHEMA_VERSION",
    "Claim",
    "ClaimVerdict",
    "ContractModel",
    "CorpusAccounting",
    "CorpusCounts",
    "CorpusEntry",
    "CorpusManifest",
    "CriticRecordDraft",
    "CriticRubric",
    "CriticTaskDraft",
    "InvestigationSpec",
    "JsonObject",
    "NonNegativeInt",
    "ObjectiveAssessment",
    "ObjectiveCriterion",
    "ObjectiveProfile",
    "PaperIdentifier",
    "PaperIdentity",
    "PositiveInt",
    "ReaderFocus",
    "ReaderRecordDraft",
    "ReaderTask",
    "ReviewFinding",
    "Rfc3339",
    "Score",
    "SearchPlan",
    "Sha256",
    "SourceLocator",
    "SourcePacket",
    "SourceSection",
    "Text",
    "canonical_json",
    "sha256_bytes",
    "sha256_json",
]
