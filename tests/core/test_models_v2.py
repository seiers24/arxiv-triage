from __future__ import annotations

import sys
import unittest
from pathlib import Path

from pydantic import ValidationError


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arxiv_triage import models  # noqa: E402


HASH_A = "a" * 64
HASH_C = "c" * 64


def with_self_hash(payload: dict[str, object], field: str) -> dict[str, object]:
    payload.pop(field, None)
    payload[field] = models.sha256_json(payload)
    return payload


def objective_payload() -> dict[str, object]:
    return with_self_hash({
        "schema_version": "2.0",
        "profile_id": "profile-example-v1",
        "component": "test-component",
        "origin": "user_authored",
        "criteria": [
            {
                "criterion_id": "example",
                "definition": "What is being judged",
                "score_type": "integer_0_5",
                "weight": 1.0,
                "gate": False,
                "anchors": {"0": "Absent", "3": "Moderate", "5": "Strong"},
            }
        ],
        "human_review_triggers": ["uncertain_high_impact"],
    }, "profile_hash")


def identity_payload() -> dict[str, object]:
    return with_self_hash({
        "schema_version": "2.0",
        "paper_id": "paper-9a45d231",
        "title": "Exact resolved title",
        "authors": ["Author One"],
        "published": None,
        "identifiers": [
            {
                "scheme": "arxiv",
                "value": "2601.01234v1",
                "url": "https://arxiv.org/abs/2601.01234",
            }
        ],
        "identity_status": "resolved_exact",
    }, "identity_hash")


NORMALIZED = "Abstract\nThe measured result is 42%.\nConclusion"
HASH_B = models.sha256_bytes(NORMALIZED.encode("utf-8"))
QUOTE = "The measured result is 42%."
QUOTE_START = NORMALIZED.index(QUOTE)
QUOTE_END = QUOTE_START + len(QUOTE)


def packet_payload() -> dict[str, object]:
    return with_self_hash({
        "schema_version": "2.0",
        "source_document_id": "src-36b7c20d",
        "paper_id": "paper-9a45d231",
        "format": "html",
        "retrieval_method": "direct",
        "source_url": "https://arxiv.org/html/2601.01234v1",
        "retrieved_at": "2026-09-12T18:06:00Z",
        "original_path": "data/original.html",
        "original_sha256": HASH_A,
        "normalized_path": "data/normalized.txt",
        "normalized_sha256": HASH_B,
        "sections": [
            {
                "section_id": "sec-0001",
                "heading": "Abstract",
                "start_char": 0,
                "end_char": len(NORMALIZED),
            }
        ],
        "warnings": [],
    }, "packet_hash")


def reader_payload(*, inferred: bool = False) -> dict[str, object]:
    locator = None
    evidence = "none_stated"
    environment = "none_stated"
    provenance = "analyst_inferred"
    if not inferred:
        locator = {
            "document_sha256": HASH_B,
            "section_id": "sec-0001",
            "start_char": QUOTE_START,
            "end_char": QUOTE_END,
            "quote": QUOTE,
        }
        evidence = "experiment"
        environment = "real_hardware"
        provenance = "paper_stated"
    return {
        "schema_version": "2.0",
        "role": "paper_reader",
        "job_type": "paper_read",
        "agent_run_id": "run-reader-a1b2c3",
        "investigation_id": "inv-20260912-01a2b3c4",
        "paper_id": "paper-9a45d231",
        "source_document_id": "src-36b7c20d",
        "input_hash": HASH_C,
        "problem": "Concise problem statement",
        "method": "Concise method statement",
        "claims": [
            {
                "claim_id": "claim-0c43e12a",
                "claim_kind": "result",
                "text": "A bounded result",
                "source_locator": locator,
                "evidence_modality": evidence,
                "execution_environment": environment,
                "provenance": provenance,
                "status": "unverified",
            }
        ],
        "warnings": [],
    }


def reader_task() -> models.ReaderTask:
    payload = {
        "schema_version": "2.0",
        "job_type": "paper_read",
        "agent_run_id": "run-reader-a1b2c3",
        "investigation_id": "inv-20260912-01a2b3c4",
        "paper_identity": identity_payload(),
        "source_packet": packet_payload(),
        "source_text": NORMALIZED,
        "focus": {
            "component": "test-component",
            "skill_hash": None,
            "questions": [],
        },
        "output_schema_version": "2.0",
    }
    return models.ReaderTask.model_validate(with_self_hash(payload, "input_hash"))


def critic_payload(*, input_hash: str | None = None) -> dict[str, object]:
    return {
        "schema_version": "2.0",
        "role": "critic",
        "job_type": "paper_critique",
        "agent_run_id": "run-critic-d4e5f6",
        "investigation_id": "inv-20260912-01a2b3c4",
        "paper_id": "paper-9a45d231",
        "reader_run_id": "run-reader-a1b2c3",
        "input_hash": input_hash or critic_task_input_hash(),
        "verdicts": [
            {
                "claim_id": "claim-0c43e12a",
                "status": "supported",
                "evidence_classification_correct": True,
                "reason": "The exact span supports the bounded claim.",
            }
        ],
        "objective_assessments": [
            {
                "criterion_id": "example",
                "score": 3,
                "reason": "Assessment bounded to the supplied profile.",
                "evidence_claim_ids": ["claim-0c43e12a"],
                "assumptions": [],
                "uncertain": False,
            }
        ],
        "human_review_reasons": [],
    }


def critic_task_payload(*, inferred: bool = False) -> dict[str, object]:
    reader = models.ReaderRecord.model_validate(reader_payload(inferred=inferred))
    return with_self_hash(
        {
            "schema_version": "2.0",
            "job_type": "paper_critique",
            "agent_run_id": "run-critic-d4e5f6",
            "investigation_id": "inv-20260912-01a2b3c4",
            "paper_identity": identity_payload(),
            "source_packet": packet_payload(),
            "source_text": NORMALIZED,
            "reader_record": reader.model_dump(),
            "objective_profile": objective_payload(),
            "critic_rubric": {"component": "test-component", "skill_hash": None},
        },
        "input_hash",
    )


def critic_task_input_hash() -> str:
    return str(critic_task_payload()["input_hash"])


def critic_task(*, inferred: bool = False) -> models.CriticTask:
    return models.CriticTask.model_validate(critic_task_payload(inferred=inferred))


def investigation_payload() -> dict[str, object]:
    return with_self_hash(
        {
            "schema_version": "2.0",
            "investigation_id": "inv-20260912-01a2b3c4",
            "kind": "test",
            "question": "What does the corpus establish?",
            "scope": {},
            "requested_outputs": ["report", "papers_csv"],
            "uncertainty_policy": "escalate",
            "created_at": "2026-09-12T18:00:00Z",
        },
        "spec_hash",
    )


def search_plan_payload() -> dict[str, object]:
    return with_self_hash(
        {
            "schema_version": "2.0",
            "search_plan_id": "search-example-v1",
            "component": "test-component",
            "providers": [],
            "inclusion_rules": [],
            "exclusion_rules": [],
            "completion_rule": {},
            "budget": {},
        },
        "search_plan_hash",
    )


def corpus_payload() -> dict[str, object]:
    search_hash = str(search_plan_payload()["search_plan_hash"])
    return with_self_hash(
        {
            "schema_version": "2.0",
            "investigation_id": "inv-20260912-01a2b3c4",
            "search_plan_hash": search_hash,
            "frozen_at": "2026-09-12T18:05:00Z",
            "entries": [
                {
                    "ordinal": 1,
                    "paper_id": "paper-9a45d231",
                    "membership_status": "included",
                    "discovery_refs": ["discovery-1"],
                    "inclusion_reason": "Within scope",
                    "exclusion_reason": None,
                    "terminal_state": None,
                }
            ],
            "counts": {
                "discovered": 1,
                "included": 1,
                "excluded": 0,
                "membership_unresolved": 0,
            },
        },
        "corpus_hash",
    )


def reviewer_task() -> models.ReviewerTask:
    critic = models.validate_critic_output(critic_task(), critic_payload())
    payload = {
        "schema_version": "2.0",
        "job_type": "corpus_review",
        "agent_run_id": "run-reviewer-g7h8i9",
        "investigation_id": "inv-20260912-01a2b3c4",
        "investigation_spec": investigation_payload(),
        "objective_profile": objective_payload(),
        "search_plan": search_plan_payload(),
        "corpus_manifest": corpus_payload(),
        "corpus_accounting": {
            "expected": 1,
            "included": 1,
            "excluded": 0,
            "membership_unresolved": 0,
            "complete": 1,
            "analysis_unresolved": 0,
            "failed": 0,
        },
        "papers": [
            {
                "paper_id": "paper-9a45d231",
                "analysis_status": "complete",
                "reader_record": critic_task().reader_record.model_dump(),
                "critic_record": critic.model_dump(),
            }
        ],
        "ranking_artifact": None,
        "reviewer_rubric": {"component": "test-component", "skill_hash": None},
    }
    return models.ReviewerTask.model_validate(with_self_hash(payload, "input_hash"))


class CoreModelsV2Tests(unittest.TestCase):
    def test_contracts_are_strict_and_forbid_unknown_fields(self) -> None:
        payload = objective_payload()
        payload["unknown"] = "not allowed"
        with self.assertRaises(ValidationError):
            models.ObjectiveProfile.model_validate(payload)

        payload = objective_payload()
        payload["criteria"][0]["gate"] = 0
        with self.assertRaises(ValidationError):
            models.ObjectiveProfile.model_validate(payload)

    def test_canonical_json_and_sha256_are_stable(self) -> None:
        left = {"z": "é", "a": [2, 1]}
        right = {"a": [2, 1], "z": "é"}
        self.assertEqual(models.canonical_json(left), models.canonical_json(right))
        self.assertEqual(models.sha256_json(left), models.sha256_json(right))
        self.assertNotIn("\\u00e9", models.canonical_json(left))
        with self.assertRaises(ValueError):
            models.canonical_json({"invalid": float("nan")})

    def test_corpus_membership_and_counts_are_consistent(self) -> None:
        payload = {
            "schema_version": "2.0",
            "investigation_id": "inv-1",
            "search_plan_hash": HASH_A,
            "frozen_at": "2026-09-12T18:05:00Z",
            "entries": [
                {
                    "ordinal": 1,
                    "paper_id": "paper-1",
                    "membership_status": "included",
                    "discovery_refs": ["discovery-1"],
                    "inclusion_reason": "Within scope",
                    "exclusion_reason": None,
                    "terminal_state": None,
                }
            ],
            "counts": {
                "discovered": 1,
                "included": 1,
                "excluded": 0,
                "membership_unresolved": 0,
            },
            "corpus_hash": HASH_B,
        }
        payload["corpus_hash"] = models.sha256_self_hash(payload, "corpus_hash")
        self.assertEqual(models.CorpusManifest.model_validate(payload).counts.included, 1)
        payload["counts"]["included"] = 0
        with self.assertRaises(ValidationError):
            models.CorpusManifest.model_validate(payload)

    def test_empty_frozen_corpus_is_representable(self) -> None:
        payload = {
            "schema_version": "2.0",
            "investigation_id": "inv-1",
            "search_plan_hash": HASH_A,
            "frozen_at": "2026-09-12T18:05:00Z",
            "entries": [],
            "counts": {
                "discovered": 0,
                "included": 0,
                "excluded": 0,
                "membership_unresolved": 0,
            },
            "corpus_hash": HASH_B,
        }
        payload["corpus_hash"] = models.sha256_self_hash(payload, "corpus_hash")
        self.assertEqual(models.CorpusManifest.model_validate(payload).entries, [])

        task_payload = {
            "schema_version": "2.0",
            "job_type": "corpus_review",
            "agent_run_id": "run-reviewer-empty",
            "investigation_id": "inv-1",
            "investigation_spec": with_self_hash(
                {
                    **investigation_payload(),
                    "investigation_id": "inv-1",
                    "spec_hash": HASH_A,
                },
                "spec_hash",
            ),
            "objective_profile": objective_payload(),
            "search_plan": with_self_hash(
                {
                    **search_plan_payload(),
                    "search_plan_hash": HASH_A,
                },
                "search_plan_hash",
            ),
            "corpus_manifest": payload,
            "corpus_accounting": {
                "expected": 0,
                "included": 0,
                "excluded": 0,
                "membership_unresolved": 0,
                "complete": 0,
                "analysis_unresolved": 0,
                "failed": 0,
            },
            "papers": [],
            "ranking_artifact": None,
            "reviewer_rubric": {
                "component": "test-component",
                "skill_hash": None,
            },
        }
        task_payload["corpus_manifest"]["search_plan_hash"] = task_payload[
            "search_plan"
        ]["search_plan_hash"]
        task_payload["corpus_manifest"]["corpus_hash"] = models.sha256_self_hash(
            task_payload["corpus_manifest"], "corpus_hash"
        )
        task_payload["input_hash"] = models.sha256_json(task_payload)
        self.assertEqual(
            models.ReviewerTask.model_validate(task_payload).papers, []
        )

    def test_reader_task_validates_exact_source_locator(self) -> None:
        task = reader_task()
        record = models.validate_reader_output(
            task, {**reader_payload(), "input_hash": task.input_hash}
        )
        self.assertIsInstance(record, models.ReaderRecord)

        bad = reader_payload()
        bad["claims"][0]["source_locator"]["quote"] = "Different text"
        with self.assertRaisesRegex(ValueError, "does not match"):
            bad["input_hash"] = task.input_hash
            models.validate_reader_output(task, bad)

    def test_reader_gateway_binds_output_to_task(self) -> None:
        bad = reader_payload()
        bad["paper_id"] = "paper-other"
        bad["input_hash"] = reader_task().input_hash
        with self.assertRaisesRegex(ValueError, "paper_id does not match task"):
            models.validate_reader_output(reader_task(), bad)

    def test_reader_gateway_parses_raw_json(self) -> None:
        record = models.validate_reader_output(
            reader_task(),
            models.canonical_json(
                {**reader_payload(), "input_hash": reader_task().input_hash}
            ),
        )
        self.assertIsInstance(record, models.ReaderRecord)

    def test_unicode_offsets_use_python_code_points(self) -> None:
        normalized = "Résumé: 速度 is high."
        quote = "速度"
        start = normalized.index(quote)
        packet_data = {
                **packet_payload(),
                "normalized_sha256": models.sha256_bytes(normalized.encode("utf-8")),
                "sections": [
                    {
                        "section_id": "sec-0001",
                        "heading": "Abstract",
                        "start_char": 0,
                        "end_char": len(normalized),
                    }
                ],
            }
        packet_data["packet_hash"] = models.sha256_self_hash(
            packet_data, "packet_hash"
        )
        packet = models.SourcePacket.model_validate(packet_data)
        packet.validate_locator(
            document_sha256=models.sha256_bytes(normalized.encode("utf-8")),
            section_id="sec-0001",
            start_char=start,
            end_char=start + len(quote),
            quote=quote,
            normalized_text=normalized,
        )

    def test_inferred_claim_has_no_locator_or_evidence(self) -> None:
        self.assertIsNone(
            models.ReaderRecord.model_validate(reader_payload(inferred=True))
            .claims[0]
            .source_locator
        )
        bad = reader_payload(inferred=True)
        bad["claims"][0]["evidence_modality"] = "experiment"
        with self.assertRaises(ValidationError):
            models.ReaderRecord.model_validate(bad)

    def test_reader_accepts_contribution_and_assumption_claim_kinds(self) -> None:
        for claim_kind in ("contribution", "assumption"):
            payload = reader_payload()
            payload["claims"][0]["claim_kind"] = claim_kind
            with self.subTest(claim_kind=claim_kind):
                record = models.ReaderRecord.model_validate(payload)
                self.assertEqual(record.claims[0].claim_kind, claim_kind)

    def test_reader_allows_no_claims_and_requires_only_warnings(self) -> None:
        payload = reader_payload()
        payload["claims"] = []
        payload["warnings"] = ["No relevant evidence was extractable."]
        record = models.ReaderRecord.model_validate(payload)
        self.assertEqual(record.claims, [])
        self.assertEqual(record.warnings, ["No relevant evidence was extractable."])

        payload["warnings"] = []
        with self.assertRaisesRegex(
            ValidationError, "without claims must include a warning"
        ):
            models.ReaderRecord.model_validate(payload)

    def test_reader_rejects_removed_parallel_collections(self) -> None:
        for field in (
            "contributions",
            "experimental_evidence",
            "limitations",
            "assumptions",
            "focused_observations",
        ):
            payload = reader_payload()
            payload[field] = []
            with self.subTest(field=field), self.assertRaises(ValidationError):
                models.ReaderRecord.model_validate(payload)

    def test_critic_covers_every_claim_and_cites_supported_claims(self) -> None:
        task = critic_task()
        record = models.validate_critic_output(task, critic_payload())
        self.assertIsInstance(record, models.CriticRecord)

        missing = critic_payload()
        missing["verdicts"] = []
        with self.assertRaisesRegex(ValueError, "exactly one verdict"):
            models.validate_critic_output(task, missing)

        unsupported = critic_payload()
        unsupported["verdicts"][0]["status"] = "unsupported"
        with self.assertRaisesRegex(ValueError, "only supported"):
            models.validate_critic_output(task, unsupported)

    def test_critic_cannot_support_claim_without_locator(self) -> None:
        task = critic_task(inferred=True)
        with self.assertRaisesRegex(ValueError, "cannot be supported"):
            models.validate_critic_output(task, critic_payload(input_hash=task.input_hash))

    def test_evidence_classification_objection_is_analysis_unresolved(self) -> None:
        task = critic_task()
        payload = critic_payload()
        payload["verdicts"][0]["evidence_classification_correct"] = False
        critic = models.validate_critic_output(task, payload)
        review_paper = {
            "paper_id": task.paper_identity.paper_id,
            "analysis_status": "complete",
            "reader_record": task.reader_record.model_dump(),
            "critic_record": critic.model_dump(),
        }
        with self.assertRaisesRegex(ValidationError, "analysis_status"):
            models.ReviewPaper.model_validate(review_paper)
        review_paper["analysis_status"] = "analysis_unresolved"
        self.assertEqual(
            models.ReviewPaper.model_validate(review_paper).analysis_status,
            "analysis_unresolved",
        )

    def test_review_accounting_rejects_invalid_totals_without_boolean(self) -> None:
        valid = {
            "expected": 2,
            "included": 2,
            "excluded": 0,
            "membership_unresolved": 0,
            "complete": 1,
            "analysis_unresolved": 1,
            "failed": 0,
        }
        self.assertTrue(models.CorpusAccounting.model_validate(valid).accounting_valid)
        valid["complete"] = 0
        with self.assertRaises(ValidationError):
            models.CorpusAccounting.model_validate(valid)

    def test_self_hash_excludes_only_own_hash_field(self) -> None:
        payload = objective_payload()
        self.assertEqual(
            payload["profile_hash"], models.sha256_self_hash(payload, "profile_hash")
        )
        payload["component"] = "changed-component"
        with self.assertRaisesRegex(ValidationError, "profile_hash does not match"):
            models.ObjectiveProfile.model_validate(payload)

    def test_reader_and_critic_tasks_embed_exact_source_text(self) -> None:
        reader = reader_task().model_dump()
        reader["source_text"] = "different"
        reader["input_hash"] = models.sha256_self_hash(reader, "input_hash")
        with self.assertRaisesRegex(ValidationError, "source_text hash does not match"):
            models.ReaderTask.model_validate(reader)

        critic = critic_task().model_dump()
        critic["source_text"] = "different"
        critic["input_hash"] = models.sha256_self_hash(critic, "input_hash")
        with self.assertRaisesRegex(ValidationError, "source_text hash does not match"):
            models.CriticTask.model_validate(critic)

        critic = critic_task().model_dump()
        critic["reader_record"]["claims"][0]["source_locator"]["quote"] = "wrong"
        critic["input_hash"] = models.sha256_self_hash(critic, "input_hash")
        with self.assertRaisesRegex(ValidationError, "quote does not match"):
            models.CriticTask.model_validate(critic)

    def test_objective_assessment_has_score_and_no_label_field(self) -> None:
        assessment = critic_payload()["objective_assessments"][0]
        assessment["label"] = None
        with self.assertRaises(ValidationError):
            models.CriticRecord.model_validate(critic_payload() | {
                "objective_assessments": [assessment]
            })

    def test_reviewer_gateway_resolves_evidence_and_human_review_refs(self) -> None:
        task = reviewer_task()
        ready = {
            "schema_version": "2.0",
            "role": "reviewer",
            "job_type": "corpus_review",
            "agent_run_id": task.agent_run_id,
            "investigation_id": task.investigation_id,
            "input_hash": task.input_hash,
            "corpus_accounting": task.corpus_accounting.model_dump(),
            "findings": [
                {
                    "finding_id": "finding-1",
                    "text": "The supported result is present in the corpus.",
                    "evidence_refs": [
                        {
                            "kind": "claim",
                            "paper_id": "paper-9a45d231",
                            "claim_id": "claim-0c43e12a",
                        }
                    ],
                    "provenance": "reviewer_inferred",
                    "uncertain": False,
                }
            ],
            "challenges": [],
            "human_review_items": [],
            "report_status": "ready",
        }
        self.assertIsInstance(
            models.validate_reviewer_output(task, ready), models.ReviewRecord
        )

        blocked = dict(ready)
        blocked["challenges"] = [
            {
                "challenge_id": "challenge-1",
                "target": {
                    "kind": "verdict",
                    "paper_id": "paper-9a45d231",
                    "claim_id": "claim-0c43e12a",
                },
                "text": "A human should inspect this bounded objection.",
                "evidence_refs": [],
                "uncertain": True,
            }
        ]
        blocked["human_review_items"] = ["challenge-1"]
        blocked["report_status"] = "blocked"
        self.assertEqual(
            models.validate_reviewer_output(task, blocked).report_status, "blocked"
        )

        blocked["human_review_items"] = ["challenge-missing"]
        with self.assertRaisesRegex(ValidationError, "must reference challenge_id"):
            models.ReviewRecord.model_validate(blocked)

    def test_run_bundle_contracts_and_trace_event_are_exact(self) -> None:
        validation = models.ValidationRecord.model_validate(
            {
                "schema_version": "2.0",
                "agent_run_id": "run-reader-1",
                "validator_version": "validator-2.0",
                "checked_at": "2026-09-12T18:10:01Z",
                "input_hash": HASH_A,
                "parsed_hash": HASH_C,
                "checks": [
                    {"check_id": "schema", "status": "passed", "detail": None}
                ],
                "errors": [],
                "referenced_hashes": [
                    {"name": "source.packet", "sha256": HASH_C}
                ],
            }
        )
        self.assertTrue(validation.validation_passed)

        outcome = models.OutcomeRecord.model_validate(
            {
                "schema_version": "2.0",
                "agent_run_id": "run-reader-1",
                "status": "completed",
                "started_at": "2026-09-12T18:10:00Z",
                "completed_at": "2026-09-12T18:10:02Z",
                "duration_ms": 2000,
                "input_path": "data/runs/run-reader-1/input.json",
                "input_hash": HASH_A,
                "raw_output_path": "data/runs/run-reader-1/raw-output.txt",
                "raw_output_hash": HASH_A,
                "validation_path": "data/runs/run-reader-1/validation.json",
                "validation_hash": HASH_C,
                "canonical_path": "data/reader/canonical.json",
                "canonical_hash": HASH_C,
                "tokens_in": 10,
                "tokens_out": 20,
                "cost_usd": 0.01,
                "error": None,
            }
        )
        self.assertEqual(outcome.status, "completed")

        run_payload = {
            **outcome.model_dump(),
            "paper_id": "paper-1",
            "role": "paper_reader",
            "job_type": "paper_read",
            "attempt_no": 1,
            "model": "model/example",
            "agent_definition_hash": HASH_A,
            "component_skill_hash": None,
            "objective_profile_hash": HASH_C,
            "investigation_id": "inv-1",
        }
        self.assertEqual(
            models.AgentRun.model_validate(run_payload).status, "completed"
        )
        run_payload["cost_usd"] = float("inf")
        with self.assertRaises(ValidationError):
            models.AgentRun.model_validate(run_payload)

        event = {
            "schema_version": "2.0",
            "event_id": "evt-run-reader-1-completed-3",
            "event_type": "agent_run.completed",
            "timestamp": "2026-09-12T18:10:02Z",
            "agent_run_id": "run-reader-1",
            "investigation_id": "inv-1",
            "paper_id": "paper-1",
            "role": "paper_reader",
            "job_type": "paper_read",
            "attempt_no": 1,
            "sequence": 3,
            "model": "model/example",
            "agent_definition_hash": HASH_A,
            "component_skill_hash": None,
            "objective_profile_hash": HASH_C,
            "input_path": "data/runs/run-reader-1/input.json",
            "input_hash": HASH_A,
            "artifact_path": "data/reader/canonical.json",
            "artifact_hash": HASH_C,
            "tokens_in": 10,
            "tokens_out": 20,
            "cost_usd": 0.01,
            "error": None,
        }
        self.assertEqual(models.TraceEvent.model_validate(event).sequence, 3)
        event["input_path"] = "../outside.json"
        with self.assertRaises(ValidationError):
            models.TraceEvent.model_validate(event)
        event["input_path"] = "."
        with self.assertRaises(ValidationError):
            models.TraceEvent.model_validate(event)

    def test_run_timestamp_order_uses_utc_instants_not_string_order(self) -> None:
        payload = {
            "schema_version": "2.0",
            "agent_run_id": "run-fractional-time",
            "status": "failed",
            "started_at": "2026-09-12T18:10:00Z",
            "completed_at": "2026-09-12T18:10:00.1Z",
            "duration_ms": 100,
            "input_path": "data/runs/run-fractional-time/input.json",
            "input_hash": HASH_A,
            "raw_output_path": None,
            "raw_output_hash": None,
            "validation_path": None,
            "validation_hash": None,
            "canonical_path": None,
            "canonical_hash": None,
            "tokens_in": None,
            "tokens_out": None,
            "cost_usd": None,
            "error": "dispatch failed",
        }
        self.assertEqual(models.OutcomeRecord.model_validate(payload).duration_ms, 100)

        payload["started_at"] = "2026-09-12T18:10:00.2Z"
        with self.assertRaisesRegex(ValidationError, "cannot precede"):
            models.OutcomeRecord.model_validate(payload)

    def test_utc_timestamp_requires_canonical_z_suffix(self) -> None:
        payload = packet_payload()
        payload["retrieved_at"] = "2026-09-12T11:06:00-07:00"
        payload["packet_hash"] = models.sha256_self_hash(payload, "packet_hash")
        with self.assertRaises(ValidationError):
            models.SourcePacket.model_validate(payload)


if __name__ == "__main__":
    unittest.main()
