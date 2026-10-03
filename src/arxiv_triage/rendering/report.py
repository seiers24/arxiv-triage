"""Render validated investigation artifacts without model calls."""

from __future__ import annotations

import csv
import io
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from arxiv_triage.models import (
    CorpusManifest,
    ObjectiveProfile,
    PaperIdentity,
    ReviewPaper,
    ReviewRecord,
    sha256_self_hash,
)


@dataclass(frozen=True, slots=True)
class RenderedOutputs:
    report: Path
    papers_csv: Path
    human_review: Path


def _atomic_write(path: Path, data: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def _verify_ranking(artifact: Mapping[str, object], profile: ObjectiveProfile) -> None:
    if artifact.get("objective_profile_hash") != profile.profile_hash:
        raise ValueError("ranking artifact does not match objective profile")
    if artifact.get("ranking_hash") != sha256_self_hash(artifact, "ranking_hash"):
        raise ValueError("ranking artifact hash is invalid")


def render_investigation(
    *,
    output_directory: Path,
    corpus_manifest: CorpusManifest,
    objective_profile: ObjectiveProfile,
    identities: Mapping[str, PaperIdentity],
    papers: Iterable[ReviewPaper],
    review_record: ReviewRecord,
    ranking_artifact: Mapping[str, object],
    component_metadata: Mapping[str, object] | None = None,
) -> RenderedOutputs:
    """Write a complete Markdown report, CSV table, and review queue."""

    if review_record.report_status == "blocked":
        raise ValueError("a blocked review cannot be rendered")
    if review_record.investigation_id != corpus_manifest.investigation_id:
        raise ValueError("review and corpus investigation IDs do not match")
    _verify_ranking(ranking_artifact, objective_profile)
    paper_by_id = {paper.paper_id: paper for paper in papers}
    rank_by_id = {
        row["paper_id"]: row
        for row in ranking_artifact.get("rows", [])
        if isinstance(row, dict) and isinstance(row.get("paper_id"), str)
    }
    component_metadata = component_metadata or {}
    entry_metadata = component_metadata.get("entries", {})
    if not isinstance(entry_metadata, Mapping):
        raise ValueError("component entry metadata must be a mapping")
    if component_metadata.get("component") == "workshop-analysis":
        counts_expected = corpus_manifest.counts.discovered
        if component_metadata.get("declared") != counts_expected:
            raise ValueError("workshop declared count must equal the core corpus count")
        if component_metadata.get("extracted") != counts_expected:
            raise ValueError("complete workshop extraction must equal the core corpus count")
        if component_metadata.get("identity_resolved") != counts_expected:
            raise ValueError("workshop identity resolution must equal the core corpus count")
        if component_metadata.get("workshop_policy_hash") != ranking_artifact.get(
            "workshop_policy_hash"
        ):
            raise ValueError("workshop policy provenance does not match ranking")

    output_directory.mkdir(parents=True, exist_ok=True)
    report_path = output_directory / "report.md"
    csv_path = output_directory / "papers.csv"
    review_path = output_directory / "human-review.json"

    counts = review_record.corpus_accounting
    report_lines = [
        f"# Investigation {corpus_manifest.investigation_id}",
        "",
        (
            f"Corpus: {counts.expected} discovered; {counts.included} included; "
            f"{counts.excluded} excluded; {counts.membership_unresolved} membership "
            f"unresolved. Analysis: {counts.complete} complete; "
            f"{counts.analysis_unresolved} unresolved; {counts.failed} failed."
        ),
        "",
        "## Accounting",
        "",
        "| Declared | Extracted | Identity resolved | Analysis complete | Analysis unresolved | Failed |",
        "|---:|---:|---:|---:|---:|---:|",
        (
            f"| {component_metadata.get('declared', counts.expected)} | "
            f"{component_metadata.get('extracted', counts.expected)} | "
            f"{component_metadata.get('identity_resolved', counts.included)} | "
            f"{counts.complete} | {counts.analysis_unresolved} | {counts.failed} |"
        ),
        "",
        "## Papers",
        "",
        "| Rank | Paper | Track | Identity | Analysis | Score | Top tier |",
        "|---:|---|---|---|---|---:|---|",
    ]
    csv_stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        csv_stream,
        fieldnames=[
            "ordinal",
            "paper_id",
            "title",
            "track_id",
            "poster_number",
            "resolution_status",
            "membership_status",
            "analysis_status",
            "rank",
            "total_score",
            "gate_passed",
            "uncertain",
            "top_tier",
            "top_tier_failures",
            "criterion_scores",
        ],
    )
    writer.writeheader()
    review_items: list[dict[str, object]] = []
    for entry in corpus_manifest.entries:
        identity = identities[entry.paper_id]
        paper = paper_by_id.get(entry.paper_id)
        ranking = rank_by_id.get(entry.paper_id, {})
        metadata = entry_metadata.get(entry.paper_id, {})
        if not isinstance(metadata, Mapping):
            raise ValueError("paper component metadata must be a mapping")
        analysis = paper.analysis_status if paper else "not_analyzed"
        rank = ranking.get("rank", "")
        score = ranking.get("total_score", "")
        report_lines.append(
            f"| {rank} | {identity.title} (`{entry.paper_id}`) | "
            f"{metadata.get('track_id', '')} | {metadata.get('resolution_status', '')} | "
            f"{analysis} | {score} | "
            f"{ranking.get('top_tier', '')} |"
        )
        writer.writerow(
            {
                "ordinal": entry.ordinal,
                "paper_id": entry.paper_id,
                "title": identity.title,
                "track_id": metadata.get("track_id", ""),
                "poster_number": metadata.get("poster_number", ""),
                "resolution_status": metadata.get("resolution_status", ""),
                "membership_status": entry.membership_status,
                "analysis_status": analysis,
                "rank": rank,
                "total_score": score,
                "gate_passed": ranking.get("gate_passed", ""),
                "uncertain": ranking.get("uncertain", ""),
                "top_tier": ranking.get("top_tier", ""),
                "top_tier_failures": ";".join(
                    str(value) for value in ranking.get("top_tier_failures", [])
                ),
                "criterion_scores": json.dumps(
                    ranking.get("criterion_scores", {}),
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            }
        )
        if paper and paper.analysis_status in {"analysis_unresolved", "failed"}:
            review_items.append(
                {
                    "kind": "paper_outcome",
                    "paper_id": paper.paper_id,
                    "status": paper.analysis_status,
                }
            )

    top_tier = [row for row in rank_by_id.values() if row.get("top_tier") is True]
    if any("top_tier" in row for row in rank_by_id.values()):
        report_lines.extend(["", "## Top tier", ""])
        if not top_tier:
            report_lines.append("No paper met every frozen top-tier threshold.")
        for row in sorted(top_tier, key=lambda value: value["rank"]):
            paper = paper_by_id.get(row["paper_id"])
            identity = identities[row["paper_id"]]
            report_lines.append(
                f"- **{identity.title}** — score {row['total_score']}."
            )
            if paper is not None and paper.critic_record is not None:
                for assessment in paper.critic_record.objective_assessments:
                    refs = ", ".join(
                        f"`{paper.paper_id}:{claim_id}`"
                        for claim_id in assessment.evidence_claim_ids
                    ) or "no supported claim reference"
                    report_lines.append(
                        f"  - `{assessment.criterion_id}` {assessment.score}/5: "
                        f"{assessment.reason} Evidence: {refs}."
                    )

        report_lines.extend(["", "### Complete score and threshold matrix", ""])
        criterion_ids = [item.criterion_id for item in objective_profile.criteria]
        report_lines.append(
            "| Rank | Paper | "
            + " | ".join(criterion_ids)
            + " | Total | Gate | Uncertain | Threshold failures |"
        )
        report_lines.append(
            "|---:|---|" + "---:|" * len(criterion_ids) + "---:|---|---|---|"
        )
        for row in sorted(rank_by_id.values(), key=lambda value: value["rank"]):
            scores = row.get("criterion_scores", {})
            report_lines.append(
                f"| {row['rank']} | {identities[row['paper_id']].title} | "
                + " | ".join(str(scores.get(item, "")) for item in criterion_ids)
                + f" | {row.get('total_score', '')} | {row.get('gate_passed', '')} | "
                + f"{row.get('uncertain', '')} | "
                + ", ".join(str(item) for item in row.get("top_tier_failures", []))
                + " |"
            )

    report_lines.extend(["", "## Per-paper evidence matrix", ""])
    report_lines.extend(
        [
            "| Paper | Supported | Unsupported | Overclaimed | Classification mismatches | Uncertain assessments | Reader warnings |",
            "|---|---:|---:|---:|---:|---:|---|",
        ]
    )
    for paper_id in [entry.paper_id for entry in corpus_manifest.entries]:
        paper = paper_by_id.get(paper_id)
        identity = identities[paper_id]
        verdicts = paper.critic_record.verdicts if paper and paper.critic_record else []
        assessments = (
            paper.critic_record.objective_assessments
            if paper and paper.critic_record
            else []
        )
        warnings = paper.reader_record.warnings if paper and paper.reader_record else []
        report_lines.append(
            f"| {identity.title} | {sum(item.status == 'supported' for item in verdicts)} | "
            f"{sum(item.status == 'unsupported' for item in verdicts)} | "
            f"{sum(item.status == 'overclaimed' for item in verdicts)} | "
            f"{sum(not item.evidence_classification_correct for item in verdicts)} | "
            f"{sum(item.uncertain for item in assessments)} | {'; '.join(warnings)} |"
        )

    report_lines.extend(["", "## Evidence", ""])
    for paper in paper_by_id.values():
        if paper.reader_record is None:
            continue
        verdicts = (
            {item.claim_id: item for item in paper.critic_record.verdicts}
            if paper.critic_record
            else {}
        )
        for claim in paper.reader_record.claims:
            verdict = verdicts.get(claim.claim_id)
            status = verdict.status if verdict else "unreviewed"
            locator = claim.source_locator
            citation = (
                f"{locator.document_sha256}:{locator.section_id}:"
                f"{locator.start_char}-{locator.end_char} — “{locator.quote}”"
                if locator
                else "analyst inference; no source span"
            )
            report_lines.append(
                f"- `{paper.paper_id}` [{status}] {claim.text} ({citation})"
            )

    report_lines.extend(["", "## Supported and challenged evidence", ""])
    if review_record.findings:
        for finding in review_record.findings:
            refs = ", ".join(
                f"{ref.kind}:{ref.paper_id}:"
                f"{getattr(ref, 'claim_id', getattr(ref, 'criterion_id', 'entry'))}"
                for ref in finding.evidence_refs
            )
            report_lines.append(
                f"- [reviewer_inferred; uncertain={finding.uncertain}] {finding.text} "
                f"Evidence: {refs}."
            )
    else:
        report_lines.append("No corpus-level findings were returned.")
    for challenge in review_record.challenges:
        report_lines.append(
            f"- Challenge `{challenge.challenge_id}` [uncertain={challenge.uncertain}]: "
            f"{challenge.text}"
        )
        review_items.append(
            {
                "kind": "review_challenge",
                "challenge_id": challenge.challenge_id,
                "text": challenge.text,
                "requires_human_review": challenge.challenge_id
                in review_record.human_review_items,
            }
        )

    report_lines.extend(["", "## Extension opportunities", ""])
    extension_rows = []
    for paper in paper_by_id.values():
        if paper.critic_record is None:
            continue
        for assessment in paper.critic_record.objective_assessments:
            if assessment.criterion_id == "extension_leverage":
                extension_rows.append((paper, assessment))
    if not extension_rows:
        report_lines.append("No extension-leverage criterion was assessed.")
    for paper, assessment in extension_rows:
        refs = ", ".join(
            f"`{paper.paper_id}:{claim_id}`"
            for claim_id in assessment.evidence_claim_ids
        ) or "no supported claim reference"
        assumptions = "; ".join(assessment.assumptions) or "none stated"
        report_lines.append(
            f"- **{identities[paper.paper_id].title}** [analyst inference; "
            f"uncertain={assessment.uncertain}]: {assessment.reason} "
            f"Evidence: {refs}. Assumptions: {assumptions}."
        )

    report_lines.extend(["", "## Unresolved, failed, and human review", ""])
    unresolved_rows = [
        paper for paper in paper_by_id.values() if paper.analysis_status != "complete"
    ]
    if not unresolved_rows:
        report_lines.append("No included paper has an unresolved or failed analysis outcome.")
    for paper in unresolved_rows:
        reasons = (
            paper.critic_record.human_review_reasons
            if paper.critic_record is not None
            else []
        )
        report_lines.append(
            f"- `{paper.paper_id}`: {paper.analysis_status}. "
            + ("; ".join(reasons) if reasons else "No critic human-review reason supplied.")
        )
    if review_record.human_review_items:
        report_lines.append(
            "- Corpus-review items: " + ", ".join(review_record.human_review_items)
        )

    report_lines.extend(["", "## Provenance", ""])
    provenance = {
        "investigation_id": corpus_manifest.investigation_id,
        "objective_profile_hash": objective_profile.profile_hash,
        "ranking_hash": ranking_artifact.get("ranking_hash"),
        "workshop_policy_hash": component_metadata.get("workshop_policy_hash"),
        "component_skill_hash": component_metadata.get("component_skill_hash"),
        "workshop_spec_hash": component_metadata.get("workshop_spec_hash"),
        "workshop_manifest_hash": component_metadata.get("workshop_manifest_hash"),
        "reviewer_run_id": review_record.agent_run_id,
    }
    report_lines.extend(
        f"- `{key}`: `{value}`" for key, value in provenance.items() if value is not None
    )

    _atomic_write(report_path, ("\n".join(report_lines) + "\n").encode("utf-8"))
    _atomic_write(csv_path, csv_stream.getvalue().encode("utf-8"))
    _atomic_write(
        review_path,
        (json.dumps(review_items, indent=2, ensure_ascii=False) + "\n").encode(
            "utf-8"
        ),
    )
    return RenderedOutputs(report_path, csv_path, review_path)


__all__ = ["RenderedOutputs", "render_investigation"]
