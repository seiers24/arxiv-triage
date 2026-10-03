"""Hash and materialize the reviewed workshop worker overlays."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from arxiv_triage.models import (
    CriticRubric,
    ReaderFocus,
    ReviewerRubric,
    sha256_bytes,
    sha256_json,
)


OVERLAY_FILES = (
    "SKILL.md",
    "references/acquisition.md",
    "references/reader-focus.md",
    "references/critic-rubric.md",
    "references/reviewer-rubric.md",
    "references/output-contract.md",
)
_NUMBERED_ITEM = re.compile(r"^\d+\.\s+(.+)$")


def component_skill_manifest(skill_directory: Path) -> dict[str, Any]:
    """Return a self-hashed manifest of every behavior-bearing overlay file."""

    files = []
    for relative_path in OVERLAY_FILES:
        content = (skill_directory / relative_path).read_bytes()
        files.append(
            {
                "path": relative_path,
                "sha256": sha256_bytes(content),
                "bytes": len(content),
            }
        )
    payload: dict[str, Any] = {
        "schema_version": "2.0",
        "component": "workshop-analysis",
        "files": files,
    }
    payload["skill_hash"] = sha256_json(payload)
    return payload


def _numbered_items(path: Path) -> list[str]:
    items: list[str] = []
    current: list[str] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _NUMBERED_ITEM.match(line)
        if match:
            if current is not None:
                items.append(" ".join(current))
            current = [match.group(1).strip()]
        elif current is not None and line.startswith("   ") and line.strip():
            current.append(line.strip())
        elif current is not None and not line.strip():
            items.append(" ".join(current))
            current = None
            break
    if current is not None:
        items.append(" ".join(current))
    return items


def materialize_workshop_overlays(
    skill_directory: Path,
) -> tuple[dict[str, Any], ReaderFocus, CriticRubric, ReviewerRubric]:
    """Build task-ready inputs from the reviewed Markdown bundle."""

    manifest = component_skill_manifest(skill_directory)
    skill_hash = manifest["skill_hash"]
    questions = _numbered_items(skill_directory / "references/reader-focus.md")
    critic_checks = _numbered_items(skill_directory / "references/critic-rubric.md")
    reviewer_checks = _numbered_items(skill_directory / "references/reviewer-rubric.md")
    if (len(questions), len(critic_checks), len(reviewer_checks)) != (8, 7, 8):
        raise ValueError("reviewed workshop overlay item counts changed")
    return (
        manifest,
        ReaderFocus(
            component="workshop-analysis",
            skill_hash=skill_hash,
            questions=questions,
        ),
        CriticRubric(
            component="workshop-analysis",
            skill_hash=skill_hash,
            checks=critic_checks,
        ),
        ReviewerRubric(
            component="workshop-analysis",
            skill_hash=skill_hash,
            checks=reviewer_checks,
        ),
    )


__all__ = [
    "OVERLAY_FILES",
    "component_skill_manifest",
    "materialize_workshop_overlays",
]
