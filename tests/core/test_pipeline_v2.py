from __future__ import annotations

import csv
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from arxiv_triage.acquisition import (
    SourceAcquisitionError,
    acquire_arxiv_source,
    acquire_pdf_source,
    freeze_source_packet,
    normalize_html,
)
from arxiv_triage.dispatch import DispatchResult, RunContext, RunExecutor
from arxiv_triage.models import (
    CorpusManifest,
    CriticRecord,
    CriticRubric,
    InvestigationSpec,
    ObjectiveProfile,
    PaperIdentity,
    PaperStateRecord,
    ReaderFocus,
    ReaderRecord,
    ReaderTask,
    ReviewPaper,
    ReviewRecord,
    ReviewerRubric,
    SearchPlan,
    sha256_json,
    validate_critic_output,
    validate_reader_output,
    validate_reviewer_output,
)
from arxiv_triage.rendering import build_ranking_artifact, render_investigation
from arxiv_triage.storage import ArtifactStore, iter_trace
from arxiv_triage.workflow import (
    analysis_status,
    prepare_critic_task,
    prepare_reader_task,
    prepare_reviewer_task,
)


def self_hash(payload: dict[str, object], field: str) -> dict[str, object]:
    payload.pop(field, None)
    payload[field] = sha256_json(payload)
    return payload


def identity(number: int) -> PaperIdentity:
    return PaperIdentity.model_validate(
        self_hash(
            {
                "schema_version": "2.0",
                "paper_id": f"paper-{number}",
                "title": f"Synthetic paper {number}",
                "authors": ["A. Author"],
                "published": None,
                "identifiers": [],
                "identity_status": "resolved_exact",
            },
            "identity_hash",
        )
    )


def objective() -> ObjectiveProfile:
    return ObjectiveProfile.model_validate(
        self_hash(
            {
                "schema_version": "2.0",
                "profile_id": "profile-synthetic",
                "component": "synthetic",
                "origin": "user_authored",
                "criteria": [
                    {
                        "criterion_id": "fit",
                        "definition": "Direct objective fit",
                        "score_type": "integer_0_5",
                        "weight": 2,
                        "gate": True,
                        "anchors": {"0": "Absent", "5": "Direct"},
                    },
                    {
                        "criterion_id": "evidence",
                        "definition": "Evidence strength",
                        "score_type": "integer_0_5",
                        "weight": 1,
                        "gate": False,
                        "anchors": {"0": "Absent", "5": "Strong"},
                    },
                ],
                "human_review_triggers": [],
            },
            "profile_hash",
        )
    )


def investigation() -> InvestigationSpec:
    return InvestigationSpec.model_validate(
        self_hash(
            {
                "schema_version": "2.0",
                "investigation_id": "inv-synthetic",
                "kind": "synthetic",
                "question": "What does the synthetic corpus establish?",
                "scope": {},
                "requested_outputs": ["report", "papers_csv"],
                "uncertainty_policy": "escalate",
                "created_at": "2026-09-13T20:00:00Z",
            },
            "spec_hash",
        )
    )


def search_plan() -> SearchPlan:
    return SearchPlan.model_validate(
        self_hash(
            {
                "schema_version": "2.0",
                "search_plan_id": "search-synthetic",
                "component": "synthetic",
                "providers": [],
                "inclusion_rules": ["All fixture papers"],
                "exclusion_rules": [],
                "completion_rule": {"kind": "fixture_exhausted"},
                "budget": {"fixture": True},
            },
            "search_plan_hash",
        )
    )


def corpus(plan: SearchPlan) -> CorpusManifest:
    entries = [
        {
            "ordinal": number,
            "paper_id": f"paper-{number}",
            "membership_status": "included",
            "discovery_refs": [f"discovery-{number}"],
            "inclusion_reason": "Included by synthetic fixture",
            "exclusion_reason": None,
            "terminal_state": None,
        }
        for number in range(1, 4)
    ]
    return CorpusManifest.model_validate(
        self_hash(
            {
                "schema_version": "2.0",
                "investigation_id": "inv-synthetic",
                "search_plan_hash": plan.search_plan_hash,
                "frozen_at": "2026-09-13T20:01:00Z",
                "entries": entries,
                "counts": {
                    "discovered": 3,
                    "included": 3,
                    "excluded": 0,
                    "membership_unresolved": 0,
                },
            },
            "corpus_hash",
        )
    )


def reader_record(task, claim_id: str) -> ReaderRecord:
    quote = "Measured speedup is 42 percent."
    start = task.source_text.index(quote)
    payload = {
        "schema_version": "2.0",
        "role": "paper_reader",
        "job_type": "paper_read",
        "agent_run_id": task.agent_run_id,
        "investigation_id": task.investigation_id,
        "paper_id": task.paper_identity.paper_id,
        "source_document_id": task.source_packet.source_document_id,
        "input_hash": task.input_hash,
        "problem": "Measure a synthetic system.",
        "method": "Evaluate a bounded fixture.",
        "claims": [
            {
                "claim_id": claim_id,
                "claim_kind": "result",
                "text": "The system reports a 42 percent speedup.",
                "source_locator": {
                    "document_sha256": task.source_packet.normalized_sha256,
                    "section_id": "sec-0001",
                    "start_char": start,
                    "end_char": start + len(quote),
                    "quote": quote,
                },
                "evidence_modality": "simulation",
                "execution_environment": "simulated_hardware",
                "provenance": "paper_stated",
                "status": "unverified",
            }
        ],
        "warnings": [],
    }
    return validate_reader_output(task, payload)


def critic_record(task, *, supported: bool) -> CriticRecord:
    claim_id = task.reader_record.claims[0].claim_id
    payload = {
        "schema_version": "2.0",
        "role": "critic",
        "job_type": "paper_critique",
        "agent_run_id": task.agent_run_id,
        "investigation_id": task.investigation_id,
        "paper_id": task.paper_identity.paper_id,
        "reader_run_id": task.reader_record.agent_run_id,
        "input_hash": task.input_hash,
        "verdicts": [
            {
                "claim_id": claim_id,
                "status": "supported" if supported else "overclaimed",
                "evidence_classification_correct": supported,
                "reason": "Fixture verdict",
            }
        ],
        "objective_assessments": [
            {
                "criterion_id": criterion,
                "score": score,
                "reason": "Fixture assessment",
                "evidence_claim_ids": [claim_id] if supported else [],
                "assumptions": [],
                "uncertain": not supported,
            }
            for criterion, score in (("fit", 5 if supported else 2), ("evidence", 4 if supported else 1))
        ],
        "human_review_reasons": [] if supported else ["Overclaim requires review"],
    }
    return validate_critic_output(task, payload)


def test_source_normalization_is_deterministic_and_ignores_script_text() -> None:
    raw = b"<html><h1>Abstract</h1><p>Chip \xce\xb1 result.</p><script>bad()</script></html>"
    first = normalize_html(raw)
    second = normalize_html(raw)
    assert first == second
    assert first.text == "Abstract\n\nChip α result."
    assert "bad" not in first.text


class _SourceFetcher:
    def __init__(self, responses: list[bytes | Exception]) -> None:
        self.responses = responses
        self.urls: list[str] = []

    def fetch(self, url: str, *, timeout_seconds: int, max_bytes: int) -> bytes:
        assert timeout_seconds == 5
        assert max_bytes == 1000
        self.urls.append(url)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class _PdfExtractor:
    def __init__(self, result: str | Exception) -> None:
        self.result = result 

    def extract(self, pdf_bytes: bytes, *, timeout_seconds: int) -> str:
        assert pdf_bytes == b"%PDF-fixture"'
        assert timeout_seconds == 5
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def arxiv_identity() -> PaperIdentity:
    payload = identity(1).model_dump(mode="json")
    payload["identifiers"] = [
        {
            "scheme": "arxiv",
            "value": "2609.00001v1",
            "url": "https://arxiv.org/abs/2609.00001v1",
        }
    ]
    payload["identity_hash"] = sha256_json(
        {key: value for key, value in payload.items() if key != "identity_hash"}
    )
    return PaperIdentity.model_validate(payload)


def proceedings_identity(*, exact: bool = True) -> PaperIdentity:
    payload = identity(2).model_dump(mode="json")
    payload["identifiers"] = [
        {
            "scheme": "proceedings",
            "value": "cvpr2026w-edge-paper-2",
            "url": "https://openaccess.thecvf.com/fixture-paper.pdf",
        }
    ]
    payload["identity_status"] = "resolved_exact" if exact else "resolved_probable"
    payload["identity_hash"] = sha256_json(
        {key: value for key, value in payload.items() if key != "identity_hash"}
    )
    return PaperIdentity.model_validate(payload)


def test_source_acquisition_uses_html_first(tmp_path: Path) -> None:
    fetcher = _SourceFetcher([b"<h1>Abstract</h1><p>Exact HTML.</p>"])
    result = acquire_arxiv_source(
        store=ArtifactStore(tmp_path),
        paper_identity=arxiv_identity(),
        abstract="Frozen abstract",
        retrieved_at="2026-09-13T20:02:00Z",
        fetcher=fetcher,
        pdf_extractor=_PdfExtractor("unused"),
        timeout_seconds=5,
        max_bytes=1000,
    )
    assert result.packet.format == "html"
    assert result.normalized_text == "Abstract\n\nExact HTML."
    assert len(fetcher.urls) == 1


def test_source_acquisition_falls_back_to_pdf_then_abstract(tmp_path: Path) -> None:
    pdf = acquire_arxiv_source(
        store=ArtifactStore(tmp_path / "pdf"),
        paper_identity=arxiv_identity(),
        abstract="Frozen abstract",
        retrieved_at="2026-09-13T20:02:00Z",
        fetcher=_SourceFetcher([RuntimeError("no html"), b"%PDF-fixture"]),
        pdf_extractor=_PdfExtractor("Extracted PDF text."),
        timeout_seconds=5,
        max_bytes=1000,
    )
    assert pdf.packet.format == "pdf_text"
    assert pdf.packet.original_path.endswith(".pdf")
    assert pdf.warnings and "HTML unavailable" in pdf.warnings[0]

    abstract = acquire_arxiv_source(
        store=ArtifactStore(tmp_path / "abstract"),
        paper_identity=arxiv_identity(),
        abstract="Frozen abstract",
        retrieved_at="2026-09-13T20:02:00Z",
        fetcher=_SourceFetcher([RuntimeError("no html"), b"%PDF-fixture"]),
        pdf_extractor=_PdfExtractor(RuntimeError("bad pdf")),
        timeout_seconds=5,
        max_bytes=1000,
    )
    assert abstract.packet.format == "abstract"
    assert len(abstract.warnings) == 2
    assert list((tmp_path / "abstract/data/papers/paper-1/acquisition").glob("pdf-*.pdf"))


def test_source_acquisition_fails_visibly_without_any_usable_source(tmp_path: Path) -> None:
    with pytest.raises(SourceAcquisitionError, match="no frozen abstract"):
        acquire_arxiv_source(
            store=ArtifactStore(tmp_path),
            paper_identity=arxiv_identity(),
            abstract=None,
            retrieved_at="2026-09-13T20:02:00Z",
            fetcher=_SourceFetcher([RuntimeError("no html"), RuntimeError("no pdf")]),
            pdf_extractor=_PdfExtractor("unused"),
            timeout_seconds=5,
            max_bytes=1000,
        )


def test_exact_bound_pdf_source_supports_non_arxiv_proceedings(tmp_path: Path) -> None:
    source_url = "https://openaccess.thecvf.com/fixture-paper.pdf"
    acquired = acquire_pdf_source(
        store=ArtifactStore(tmp_path),
        paper_identity=proceedings_identity(),
        source_url=source_url,
        retrieved_at="2026-09-13T20:02:00Z",
        fetcher=_SourceFetcher([b"%PDF-fixture"]),
        pdf_extractor=_PdfExtractor("Proceedings PDF text."),
        timeout_seconds=5,
        max_bytes=1000,
    )
    assert acquired.packet.format == "pdf_text"
    assert acquired.packet.retrieval_method == "direct"
    assert acquired.packet.source_url == source_url
    assert acquired.normalized_text == "Proceedings PDF text."


def test_exact_pdf_source_rejects_unbound_or_probable_identity(tmp_path: Path) -> None:
    with pytest.raises(SourceAcquisitionError, match="not bound"):
        acquire_pdf_source(
            store=ArtifactStore(tmp_path),
            paper_identity=proceedings_identity(),
            source_url="https://example.test/unbound.pdf",
            retrieved_at="2026-09-13T20:02:00Z",
        )
    with pytest.raises(SourceAcquisitionError, match="resolved-exact"):
        acquire_pdf_source(
            store=ArtifactStore(tmp_path),
            paper_identity=proceedings_identity(exact=False),
            source_url="https://openaccess.thecvf.com/fixture-paper.pdf",
            retrieved_at="2026-09-13T20:02:00Z",
        )


def test_exact_pdf_source_preserves_invalid_response_bytes(tmp_path: Path) -> None:
    with pytest.raises(SourceAcquisitionError, match="response preserved"):
        acquire_pdf_source(
            store=ArtifactStore(tmp_path),
            paper_identity=proceedings_identity(),
            source_url="https://openaccess.thecvf.com/fixture-paper.pdf",
            retrieved_at="2026-09-13T20:02:00Z",
            fetcher=_SourceFetcher([b"%PDF-fixture"]),
            pdf_extractor=_PdfExtractor(RuntimeError("bad PDF")),
            timeout_seconds=5,
            max_bytes=1000,
        )
    assert list((tmp_path / "data/papers/paper-2/acquisition").glob("pdf-*.pdf"))


def test_three_paper_investigation_runs_from_source_packets_to_report(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path)
    profile = objective()
    spec = investigation()
    plan = search_plan()
    manifest = corpus(plan)
    identities = {f"paper-{number}": identity(number) for number in range(1, 4)}
    base = "data/investigations/inv-synthetic"
    store.write_json(f"{base}/investigation.json", spec)
    store.write_json(f"{base}/objective-profile.json", profile)
    store.write_json(f"{base}/search-plan.json", plan)
    store.write_json(f"{base}/corpus.json", manifest)
    store.write_json(f"data/objective-profiles/{profile.profile_hash}.json", profile)
    store.write_json(f"data/search-plans/{plan.search_plan_hash}.json", plan)
    for paper in identities.values():
        store.write_json(f"data/papers/{paper.paper_id}/identity.json", paper)
    canonical: list[tuple[ReaderRecord, CriticRecord]] = []
    for number in (1, 2):
        paper = identities[f"paper-{number}"]
        packet, text = freeze_source_packet(
            store=store,
            paper_identity=paper,
            source_format="abstract" if number == 1 else "pdf_text",
            original_bytes=b"Measured speedup is 42 percent.",
            retrieved_at="2026-09-13T20:02:00Z",
            retrieval_method="direct" if number == 1 else "fallback",
            source_url=None,
            warnings=() if number == 1 else ("HTML unavailable; PDF text used",),
        )
        read_task = prepare_reader_task(
            agent_run_id=f"run-reader-{number}",
            investigation_id="inv-synthetic",
            paper_identity=paper,
            source_packet=packet,
            source_text=text,
            focus=ReaderFocus(component="synthetic", skill_hash=None, questions=[]),
        )
        expected_reader = reader_record(read_task, f"claim-{number}")
        reader_result = RunExecutor(str(tmp_path)).execute(
            task=read_task,
            context=RunContext(
                investigation_id="inv-synthetic",
                paper_id=paper.paper_id,
                screening_batch_id=None,
                role="paper_reader",
                job_type="paper_read",
                attempt_no=1,
                model="fixture-model",
                agent_definition_hash="a" * 64,
                component_skill_hash=None,
                objective_profile_hash=None,
                canonical_path=f"{base}/papers/{paper.paper_id}/reader/canonical.json",
            ),
            validator=validate_reader_output,
            dispatcher=_FixtureDispatcher(
                json.dumps(expected_reader.model_dump(mode="json")).encode()
            ),
        )
        reader = ReaderRecord.model_validate(reader_result.canonical_record)
        critique_task = prepare_critic_task(
            agent_run_id=f"run-critic-{number}",
            investigation_id="inv-synthetic",
            paper_identity=paper,
            source_packet=packet,
            source_text=text,
            reader_record=reader,
            objective_profile=profile,
            critic_rubric=CriticRubric(
                component="synthetic", skill_hash=None, checks=[]
            ),
        )
        expected_critic = critic_record(critique_task, supported=number == 1)
        critic_result = RunExecutor(str(tmp_path)).execute(
            task=critique_task,
            context=RunContext(
                investigation_id="inv-synthetic",
                paper_id=paper.paper_id,
                screening_batch_id=None,
                role="critic",
                job_type="paper_critique",
                attempt_no=1,
                model="fixture-model",
                agent_definition_hash="b" * 64,
                component_skill_hash=None,
                objective_profile_hash=profile.profile_hash,
                canonical_path=f"{base}/papers/{paper.paper_id}/critic/canonical.json",
            ),
            validator=validate_critic_output,
            dispatcher=_FixtureDispatcher(
                json.dumps(expected_critic.model_dump(mode="json")).encode()
            ),
        )
        critique = CriticRecord.model_validate(critic_result.canonical_record)
        canonical.append((reader, critique))

    ranking = build_ranking_artifact(profile, [item[1] for item in canonical])
    store.write_json(f"{base}/ranking.json", ranking)
    assert [row["paper_id"] for row in ranking["rows"]] == ["paper-1", "paper-2"]
    papers = [
        ReviewPaper(
            paper_id="paper-1",
            analysis_status=analysis_status(canonical[0][1]),
            reader_record=canonical[0][0],
            critic_record=canonical[0][1],
        ),
        ReviewPaper(
            paper_id="paper-2",
            analysis_status=analysis_status(canonical[1][1]),
            reader_record=canonical[1][0],
            critic_record=canonical[1][1],
        ),
        ReviewPaper(
            paper_id="paper-3",
            analysis_status="failed",
            reader_record=None,
            critic_record=None,
        ),
    ]
    for number, (reader, critique) in enumerate(canonical, start=1):
        packet_id = ReaderTask.model_validate_json(
            store.resolve(
                store.run_bundle("inv-synthetic", f"run-reader-{number}").input
            ).read_bytes()
        ).source_packet.source_document_id
        state_payload = {
            "schema_version": "2.0",
            "investigation_id": "inv-synthetic",
            "paper_id": f"paper-{number}",
            "terminal_state": analysis_status(critique),
            "source_document_id": packet_id,
            "reader_run_id": reader.agent_run_id,
            "critic_run_id": critique.agent_run_id,
            "error": None,
            "completed_at": "2026-09-13T20:03:00Z",
        }
        state_payload["state_hash"] = sha256_json(state_payload)
        store.write_json(
            f"{base}/paper-state/paper-{number}.json",
            PaperStateRecord.model_validate(state_payload),
        )
    failed_payload = {
        "schema_version": "2.0",
        "investigation_id": "inv-synthetic",
        "paper_id": "paper-3",
        "terminal_state": "failed",
        "source_document_id": None,
        "reader_run_id": None,
        "critic_run_id": None,
        "error": "fixture source acquisition failure",
        "completed_at": "2026-09-13T20:03:00Z",
    }
    failed_payload["state_hash"] = sha256_json(failed_payload)
    store.write_json(
        f"{base}/paper-state/paper-3.json",
        PaperStateRecord.model_validate(failed_payload),
    )
    review_task = prepare_reviewer_task(
        agent_run_id="run-reviewer-1",
        investigation_spec=spec,
        objective_profile=profile,
        search_plan=plan,
        corpus_manifest=manifest,
        papers=papers,
        ranking_artifact=ranking,
        reviewer_rubric=ReviewerRubric(
            component="synthetic", skill_hash=None, checks=[]
        ),
    )
    expected_review = validate_reviewer_output(
        review_task,
        {
            "schema_version": "2.0",
            "role": "reviewer",
            "job_type": "corpus_review",
            "agent_run_id": review_task.agent_run_id,
            "investigation_id": review_task.investigation_id,
            "input_hash": review_task.input_hash,
            "corpus_accounting": review_task.corpus_accounting.model_dump(),
            "findings": [
                {
                    "finding_id": "finding-1",
                    "text": "The corpus contains one supported result.",
                    "evidence_refs": [
                        {"kind": "verdict", "paper_id": "paper-1", "claim_id": "claim-1"}
                    ],
                    "provenance": "reviewer_inferred",
                    "uncertain": False,
                }
            ],
            "challenges": [],
            "human_review_items": [],
            "report_status": "ready_with_warnings",
        },
    )
    review_result = RunExecutor(str(tmp_path)).execute(
        task=review_task,
        context=RunContext(
            investigation_id="inv-synthetic",
            paper_id=None,
            screening_batch_id=None,
            role="reviewer",
            job_type="corpus_review",
            attempt_no=1,
            model="fixture-model",
            agent_definition_hash="c" * 64,
            component_skill_hash=None,
            objective_profile_hash=profile.profile_hash,
            canonical_path=f"{base}/review/canonical.json",
        ),
        validator=validate_reviewer_output,
        dispatcher=_FixtureDispatcher(
            json.dumps(expected_review.model_dump(mode="json")).encode()
        ),
    )
    review = ReviewRecord.model_validate(review_result.canonical_record)
    outputs = render_investigation(
        output_directory=tmp_path / "out/inv-synthetic",
        corpus_manifest=review_task.corpus_manifest,
        objective_profile=profile,
        identities=identities,
        papers=papers,
        review_record=review,
        ranking_artifact=ranking,
        component_metadata={
            "component": "workshop-analysis",
            "declared": 3,
            "extracted": 3,
            "identity_resolved": 3,
            "workshop_policy_hash": None,
            "component_skill_hash": "d" * 64,
            "entries": {
                f"paper-{number}": {
                    "track_id": "long" if number < 3 else "short",
                    "poster_number": number,
                    "resolution_status": "resolved_exact",
                }
                for number in range(1, 4)
            },
        },
    )
    report = outputs.report.read_text(encoding="utf-8")
    assert "3 discovered" in report
    assert "1 complete; 1 unresolved; 1 failed" in report
    assert "Measured speedup is 42 percent." in report
    assert "## Per-paper evidence matrix" in report
    assert "## Extension opportunities" in report
    assert "## Provenance" in report
    assert "Identity resolved" in report
    with outputs.papers_csv.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 3
    assert {row["analysis_status"] for row in rows} == {
        "complete",
        "analysis_unresolved",
        "failed",
    }
    assert {row["track_id"] for row in rows} == {"long", "short"}
    assert all(row["resolution_status"] == "resolved_exact" for row in rows)

    repository_root = Path(__file__).resolve().parents[2]
    ranked = subprocess.run(
        [
            sys.executable,
            str(repository_root / "scripts/rank.py"),
            "inv-synthetic",
            "--root",
            str(tmp_path),
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    assert ranked.returncode == 0, ranked.stderr
    rendered = subprocess.run(
        [
            sys.executable,
            str(repository_root / "scripts/render.py"),
            "inv-synthetic",
            "--root",
            str(tmp_path),
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    assert rendered.returncode == 0, rendered.stderr
    rebuilt = subprocess.run(
        [
            sys.executable,
            str(repository_root / "scripts/db.py"),
            "rebuild",
            "--root",
            str(tmp_path),
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    assert rebuilt.returncode == 0, rebuilt.stderr
    with sqlite3.connect(tmp_path / "data/triage-v2.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0] == 5
        assert connection.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM review_records").fetchone()[0] == 1
        assert connection.execute(
            "SELECT status FROM investigations WHERE investigation_id = 'inv-synthetic'"
        ).fetchone()[0] == "complete_with_warnings"


def test_renderer_refuses_blocked_review(tmp_path: Path) -> None:
    profile = objective()
    plan = search_plan()
    manifest = corpus(plan)
    blocked = ReviewRecord.model_validate(
        {
            "schema_version": "2.0",
            "role": "reviewer",
            "job_type": "corpus_review",
            "agent_run_id": "run-reviewer-blocked",
            "investigation_id": "inv-synthetic",
            "input_hash": "a" * 64,
            "corpus_accounting": {
                "expected": 3,
                "included": 3,
                "excluded": 0,
                "membership_unresolved": 0,
                "complete": 0,
                "analysis_unresolved": 0,
                "failed": 3,
            },
            "findings": [],
            "challenges": [
                {
                    "challenge_id": "challenge-1",
                    "target": {"kind": "corpus_entry", "paper_id": "paper-1"},
                    "text": "Cannot publish",
                    "evidence_refs": [],
                    "uncertain": True,
                }
            ],
            "human_review_items": ["challenge-1"],
            "report_status": "blocked",
        }
    )
    with pytest.raises(ValueError, match="cannot be rendered"):
        render_investigation(
            output_directory=tmp_path / "out",
            corpus_manifest=manifest,
            objective_profile=profile,
            identities={f"paper-{number}": identity(number) for number in range(1, 4)},
            papers=[],
            review_record=blocked,
            ranking_artifact=build_ranking_artifact(profile, []),
        )


class _FixtureDispatcher:
    def __init__(self, raw_output: bytes) -> None:
        self.raw_output = raw_output

    def dispatch(self, task) -> DispatchResult:
        del task
        return DispatchResult(self.raw_output, tokens_in=10, tokens_out=5, cost_usd=0.01)


class _FailingDispatcher:
    def dispatch(self, task) -> DispatchResult:
        del task
        raise RuntimeError("fixture transport failure")


def executor_reader_task(tmp_path: Path):
    store = ArtifactStore(tmp_path)
    paper = identity(1)
    packet, text = freeze_source_packet(
        store=store,
        paper_identity=paper,
        source_format="abstract",
        original_bytes=b"Measured speedup is 42 percent.",
        retrieved_at="2026-09-13T20:02:00Z",
        retrieval_method="fallback",
        source_url=None,
    )
    return prepare_reader_task(
        agent_run_id="run-reader-executor",
        investigation_id="inv-synthetic",
        paper_identity=paper,
        source_packet=packet,
        source_text=text,
        focus=ReaderFocus(component="synthetic", skill_hash=None, questions=[]),
    )


def executor_context() -> RunContext:
    return RunContext(
        investigation_id="inv-synthetic",
        paper_id="paper-1",
        screening_batch_id=None,
        role="paper_reader",
        job_type="paper_read",
        attempt_no=1,
        model="fixture-model",
        agent_definition_hash="a" * 64,
        component_skill_hash=None,
        objective_profile_hash=None,
        canonical_path=(
            "data/investigations/inv-synthetic/papers/paper-1/reader/canonical.json"
        ),
    )


def test_run_executor_preserves_and_promotes_valid_output(tmp_path: Path) -> None:
    task = executor_reader_task(tmp_path)
    raw = json.dumps(reader_record(task, "claim-executor").model_dump()).encode()
    result = RunExecutor(str(tmp_path)).execute(
        task=task,
        context=executor_context(),
        validator=validate_reader_output,
        dispatcher=_FixtureDispatcher(raw),
    )
    assert result.run.status == "completed"
    assert result.canonical_record is not None
    bundle = ArtifactStore(tmp_path).run_bundle("inv-synthetic", task.agent_run_id)
    assert ArtifactStore(tmp_path).resolve(bundle.raw_output).read_bytes() == raw
    events = list(iter_trace(tmp_path / "logs/trace.jsonl"))
    assert [event["event_type"] for event in events] == [
        "agent_run.started",
        "agent_run.output_received",
        "agent_run.completed",
    ]


def test_run_executor_preserves_invalid_output_as_terminal_invalid(tmp_path: Path) -> None:
    task = executor_reader_task(tmp_path)
    result = RunExecutor(str(tmp_path)).execute(
        task=task,
        context=executor_context(),
        validator=validate_reader_output,
        dispatcher=_FixtureDispatcher(b"{}"),
    )
    assert result.run.status == "invalid"
    assert result.canonical_record is None
    assert result.run.canonical_path is None
    bundle = ArtifactStore(tmp_path).run_bundle("inv-synthetic", task.agent_run_id)
    assert ArtifactStore(tmp_path).resolve(bundle.raw_output).read_bytes() == b"{}"
    assert ArtifactStore(tmp_path).resolve(bundle.validation).is_file()
    assert [event["event_type"] for event in iter_trace(tmp_path / "logs/trace.jsonl")][-1] == (
        "agent_run.invalid"
    )


def test_run_executor_records_transport_failure_without_output(tmp_path: Path) -> None:
    task = executor_reader_task(tmp_path)
    result = RunExecutor(str(tmp_path)).execute(
        task=task,
        context=executor_context(),
        validator=validate_reader_output,
        dispatcher=_FailingDispatcher(),
    )
    assert result.run.status == "failed"
    assert result.run.raw_output_path is None
    bundle = ArtifactStore(tmp_path).run_bundle("inv-synthetic", task.agent_run_id)
    assert not ArtifactStore(tmp_path).resolve(bundle.raw_output).exists()
    assert [event["event_type"] for event in iter_trace(tmp_path / "logs/trace.jsonl")] == [
        "agent_run.started",
        "agent_run.failed",
    ]
