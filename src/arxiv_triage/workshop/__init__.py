"""Workshop-analysis component."""

from .extract import parse_known_workshop_url
from .models import (
    WorkshopAccounting,
    WorkshopCorpusManifest,
    WorkshopEntry,
    WorkshopRankingPolicy,
    WorkshopSourceSpan,
    WorkshopSpec,
    WorkshopTrack,
)
from .proceedings import parse_cvf_proceedings_pages
from .rank import build_workshop_ranking
from .overlays import component_skill_manifest, materialize_workshop_overlays
from .resolve import candidate_set_from_workshop, normalized_title, resolve_exact_titles

__all__ = [
    "WorkshopAccounting",
    "WorkshopCorpusManifest",
    "WorkshopEntry",
    "WorkshopRankingPolicy",
    "WorkshopSourceSpan",
    "WorkshopSpec",
    "WorkshopTrack",
    "parse_known_workshop_url",
    "parse_cvf_proceedings_pages",
    "candidate_set_from_workshop",
    "build_workshop_ranking",
    "component_skill_manifest",
    "materialize_workshop_overlays",
    "normalized_title",
    "resolve_exact_titles",
]
