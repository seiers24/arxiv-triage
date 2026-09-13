from __future__ import annotations

import sys
import unittest
from pathlib import Path

from pydantic import ValidationError


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arxiv_triage import models  # noqa: E402


HASH_A = "a" * 64
HASH_C = "c" * 64


def objective_payload() -> dict[str, object]:
    return {
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
        "profile_hash": HASH_A,
    }


def identity_payload() -> dict[str, object]:
    return {
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
        "identity_hash": HASH_A,
    }


NORMALIZED = "Abstract\nThe measured result is 42%.\nConclusion"
HASH_B = models.sha256_bytes(NORMALIZED.encode("utf-8"))
QUOTE = "The measured result is 42%."
QUOTE_START = NORMALIZED.index(QUOTE)
QUOTE_END = QUOTE_START + len(QUOTE)


def packet_payload() -> dict[str, object]:
    return {
        "schema_version": "2.0",
        "source_document_id": "src-36b7c20d",
        "paper_id": "paper-9a45d231",
        "format": "arxiv_html",
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
        "packet_hash": HASH_C,
    }


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
        "contributions": [],
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
        "experimental_evidence": [],
        "limitations": [],
        "assumptions": [],
        "focused_observations": [],
    }


def reader_task() -> models.ReaderTask:
    return models.ReaderTask.model_validate(
        {
            "schema_version": "2.0",
            "job_type": "paper_read",
            "agent_run_id": "run-reader-a1b2c3",
            "investigation_id": "inv-20260912-01a2b3c4",
            "paper_identity": identity_payload(),
            "source_packet": packet_payload(),
            "focus": {
                "component": "test-component",
                "skill_hash": None,
                "questions": [],
            },
            "output_schema_version": "2.0",
            "input_hash": HASH_C,
        }
    )


def critic_payload() -> dict[str, object]:
    return {
        "schema_version": "2.0",
        "role": "critic",
        "job_type": "paper_critique",
        "agent_run_id": "run-critic-d4e5f6",
        "investigation_id": "inv-20260912-01a2b3c4",
        "paper_id": "paper-9a45d231",
        "reader_run_id": "run-reader-a1b2c3",
        "input_hash": HASH_A,
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
                "label": None,
                "reason": "Assessment bounded to the supplied profile.",
                "evidence_claim_ids": ["claim-0c43e12a"],
                "assumptions": [],
                "uncertain": False,
            }
        ],
        "human_review_required": False,
        "human_review_reasons": [],
    }


def critic_task(*, inferred: bool = False) -> models.CriticTaskDraft:
    reader = models.ReaderRecordDraft.model_validate(reader_payload(inferred=inferred))
    return models.CriticTaskDraft.model_validate(
        {
            "schema_version": "2.0",
            "job_type": "paper_critique",
            "agent_run_id": "run-critic-d4e5f6",
            "investigation_id": "inv-20260912-01a2b3c4",
            "paper_identity": identity_payload(),
            "source_packet": packet_payload(),
            "reader_record": reader.model_dump(),
            "objective_profile": objective_payload(),
            "critic_rubric": {"component": "test-component", "skill_hash": None},
            "input_hash": HASH_A,
        }
    )


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
                "unresolved": 0,
                "failed": 0,
            },
            "corpus_hash": HASH_B,
        }
        self.assertEqual(models.CorpusManifest.model_validate(payload).counts.included, 1)
        payload["counts"]["included"] = 0
        with self.assertRaises(ValidationError):
            models.CorpusManifest.model_validate(payload)

    def test_reader_task_validates_exact_source_locator(self) -> None:
        task = reader_task()
        record = models.ReaderRecordDraft.model_validate(reader_payload())
        self.assertIs(task.validate_record(record, normalized_text=NORMALIZED), record)

        bad = reader_payload()
        bad["claims"][0]["source_locator"]["quote"] = "Different text"
        record = models.ReaderRecordDraft.model_validate(bad)
        with self.assertRaisesRegex(ValueError, "does not match"):
            task.validate_record(record, normalized_text=NORMALIZED)

    def test_unicode_offsets_use_python_code_points(self) -> None:
        normalized = "Résumé: 速度 is high."
        quote = "速度"
        start = normalized.index(quote)
        packet = models.SourcePacket.model_validate(
            {
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
        )
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
            models.ReaderRecordDraft.model_validate(reader_payload(inferred=True))
            .claims[0]
            .source_locator
        )
        bad = reader_payload(inferred=True)
        bad["claims"][0]["evidence_modality"] = "experiment"
        with self.assertRaises(ValidationError):
            models.ReaderRecordDraft.model_validate(bad)

    def test_critic_covers_every_claim_and_cites_supported_claims(self) -> None:
        task = critic_task()
        record = models.CriticRecordDraft.model_validate(critic_payload())
        self.assertIs(task.validate_record(record), record)

        missing = critic_payload()
        missing["verdicts"] = []
        with self.assertRaisesRegex(ValueError, "exactly one verdict"):
            task.validate_record(models.CriticRecordDraft.model_validate(missing))

        unsupported = critic_payload()
        unsupported["verdicts"][0]["status"] = "unsupported"
        with self.assertRaisesRegex(ValueError, "only supported"):
            task.validate_record(models.CriticRecordDraft.model_validate(unsupported))

    def test_critic_cannot_support_claim_without_locator(self) -> None:
        task = critic_task(inferred=True)
        with self.assertRaisesRegex(ValueError, "cannot be supported"):
            task.validate_record(models.CriticRecordDraft.model_validate(critic_payload()))

    def test_review_accounting_flag_must_match_totals(self) -> None:
        valid = {
            "expected": 2,
            "complete": 1,
            "unresolved": 1,
            "failed": 0,
            "accounting_valid": True,
        }
        self.assertTrue(models.CorpusAccounting.model_validate(valid).accounting_valid)
        valid["accounting_valid"] = False
        with self.assertRaises(ValidationError):
            models.CorpusAccounting.model_validate(valid)


if __name__ == "__main__":
    unittest.main()
