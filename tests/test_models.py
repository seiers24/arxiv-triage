from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import validate as models  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]


def objective_data() -> dict[str, object]:
    return json.loads((ROOT / "objectives/personal-research.json").read_text())


def paper_data() -> dict[str, object]:
    paper: dict[str, object] = {
        "schema_version": "1.0",
        "arxiv_id": "2601.01234v1",
        "title": "Illustrative Memory System Study",
        "abstract": (
            "We evaluate the design in a trace-driven simulator and report "
            "lower memory traffic than the baseline."
        ),
        "authors": ["Example Author"],
        "published": "2026-01-05T12:00:00Z",
        "updated": None,
        "journal_reference": None,
        "doi": None,
    }
    paper["input_hash"] = models.sha256_json(paper)
    return paper


def reader_data(paper: models.FrozenPaper, objective: models.ObjectiveProfile) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "role": "reader",
        "arxiv_id": paper.arxiv_id,
        "input_hash": paper.input_hash,
        "objective_id": objective.objective_id,
        "objective_hash": objective.objective_hash,
        "problem": "Memory traffic limits the target workload.",
        "method": "The paper evaluates a traffic-reduction technique in a simulator.",
        "technical_importance": 3,
        "objective_relevance": 4,
        "extendable": True,
        "reason": "The method is important, relevant to memory systems, and testable.",
        "relevance_category": "memory_systems",
        "relevance_claim_indices": [0],
        "relevance_assumptions": [
            "Lower modeled traffic may reduce pressure on a deployed memory hierarchy."
        ],
        "claims": [
            {
                "text": "The simulator reports lower memory traffic than the baseline.",
                "source_span": (
                    "We evaluate the design in a trace-driven simulator and report "
                    "lower memory traffic than the baseline."
                ),
                "evidence_type": "simulation",
                "provenance": "preprint",
                "status": "unverified",
            }
        ],
        "extension_proposal": {
            "provenance": "inferred",
            "hypothesis": "The traffic reduction persists on physical hardware.",
            "smallest_useful_experiment": "Replay the workload on one testbed.",
            "comparison_baseline": "The unmodified configuration.",
            "success_metric": "Lower measured traffic without lower throughput.",
        },
    }


def critic_data(
    paper: models.FrozenPaper,
    objective: models.ObjectiveProfile,
    *,
    status: str = "supported",
    justified: bool = True,
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "role": "critic",
        "arxiv_id": paper.arxiv_id,
        "objective_id": objective.objective_id,
        "objective_hash": objective.objective_hash,
        "reader_run_id": "reader-run-01",
        "verdicts": [
            {
                "claim_index": 0,
                "status": status,
                "reason": "The source span supports the bounded reader claim.",
            }
        ],
        "objective_relevance_assessment": {
            "justified": justified,
            "reason": "The linked claim supports the selected relevance category.",
        },
    }


class ModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.objective = models.ObjectiveProfile.model_validate(objective_data())
        self.paper = models.FrozenPaper.model_validate(paper_data())
        self.reader_dispatch = models.ReaderDispatch(
            schema_version="1.0",
            paper=self.paper,
            objective=self.objective,
            objective_hash=self.objective.objective_hash,
        )

    def test_objective_hash_is_canonical(self) -> None:
        reordered = dict(reversed(list(objective_data().items())))
        self.assertEqual(models.sha256_json(reordered), self.objective.objective_hash)

    def test_rejects_unknown_fields_and_non_strict_scores(self) -> None:
        unknown = objective_data()
        unknown["unexpected"] = True
        with self.assertRaises(ValidationError):
            models.ObjectiveProfile.model_validate(unknown)

        record = reader_data(self.paper, self.objective)
        record["technical_importance"] = True
        with self.assertRaises(ValidationError):
            models.ReaderRecord.model_validate(record)

    def test_frozen_paper_hash_must_match(self) -> None:
        changed = paper_data()
        changed["title"] = "Altered title"
        with self.assertRaises(ValidationError):
            models.FrozenPaper.model_validate(changed)

    def test_reader_record_validates_against_dispatch(self) -> None:
        record = self.reader_dispatch.validate_record(
            reader_data(self.paper, self.objective)
        )
        self.assertEqual(record.relevance_category, "memory_systems")

    def test_reader_rejects_unknown_category_and_bad_span(self) -> None:
        unknown_category = reader_data(self.paper, self.objective)
        unknown_category["relevance_category"] = "undeclared_category"
        with self.assertRaisesRegex(ValueError, "not declared"):
            self.reader_dispatch.validate_record(unknown_category)

        bad_span = reader_data(self.paper, self.objective)
        bad_span["claims"][0]["source_span"] = "Text absent from the abstract."
        with self.assertRaisesRegex(ValueError, "not in the frozen abstract"):
            self.reader_dispatch.validate_record(bad_span)

    def test_reader_internal_cross_field_rules(self) -> None:
        record = reader_data(self.paper, self.objective)
        record["objective_relevance"] = 0
        with self.assertRaises(ValidationError):
            models.ReaderRecord.model_validate(record)

        record = reader_data(self.paper, self.objective)
        record["extendable"] = False
        with self.assertRaises(ValidationError):
            models.ReaderRecord.model_validate(record)

    def test_claim_null_span_rules(self) -> None:
        claim = {
            "text": "An analyst inference.",
            "source_span": None,
            "evidence_type": "simulation",
            "provenance": "inferred",
            "status": "unverified",
        }
        with self.assertRaises(ValidationError):
            models.Claim.model_validate(claim)

    def test_critic_validates_identity_coverage_and_linked_rejections(self) -> None:
        reader = self.reader_dispatch.validate_record(
            reader_data(self.paper, self.objective)
        )
        dispatch = models.CriticDispatch(
            schema_version="1.0",
            paper=self.paper,
            objective=self.objective,
            objective_hash=self.objective.objective_hash,
            reader_record=reader,
            reader_run_id="reader-run-01",
        )
        valid = dispatch.validate_record(critic_data(self.paper, self.objective))
        self.assertEqual(valid.verdicts[0].status, "supported")

        rejected = critic_data(
            self.paper,
            self.objective,
            status="unsupported",
            justified=True,
        )
        with self.assertRaisesRegex(ValueError, "linked claim is rejected"):
            dispatch.validate_record(rejected)

        missing = critic_data(self.paper, self.objective)
        missing["verdicts"] = []
        with self.assertRaisesRegex(ValueError, "exactly one verdict"):
            dispatch.validate_record(missing)

    def test_critic_cannot_support_a_null_span(self) -> None:
        reader_payload = reader_data(self.paper, self.objective)
        reader_payload["objective_relevance"] = 0
        reader_payload["relevance_category"] = None
        reader_payload["relevance_claim_indices"] = []
        reader_payload["claims"][0] = {
            "text": "The technique may help a different deployment.",
            "source_span": None,
            "evidence_type": "none_stated",
            "provenance": "inferred",
            "status": "unverified",
        }
        reader = self.reader_dispatch.validate_record(reader_payload)
        dispatch = models.CriticDispatch(
            schema_version="1.0",
            paper=self.paper,
            objective=self.objective,
            objective_hash=self.objective.objective_hash,
            reader_record=reader,
            reader_run_id="reader-run-01",
        )
        with self.assertRaisesRegex(ValueError, "cannot be supported"):
            dispatch.validate_record(critic_data(self.paper, self.objective))

    def test_trace_outcome_rules(self) -> None:
        base = {
            "schema_version": "1.0",
            "agent_run_id": "reader-run-01",
            "arxiv_id": self.paper.arxiv_id,
            "role": "reader",
            "timestamp": "2026-09-08T01:00:00Z",
            "model": "example-model",
            "agent_hash": "a" * 64,
            "input_hash": self.paper.input_hash,
            "objective_id": self.objective.objective_id,
            "objective_hash": self.objective.objective_hash,
            "artifact_path": "data/records/example.json",
            "artifact_hash": "b" * 64,
            "validation_pass": True,
            "retry_count": 0,
            "verdict_summary": None,
            "tokens_in": None,
            "tokens_out": None,
            "cost_usd": None,
            "error": None,
        }
        event = models.TraceEvent.model_validate(base)
        self.assertTrue(event.validation_pass)

        invalid = copy.deepcopy(base)
        invalid["artifact_path"] = None
        with self.assertRaises(ValidationError):
            models.TraceEvent.model_validate(invalid)


if __name__ == "__main__":
    unittest.main()
