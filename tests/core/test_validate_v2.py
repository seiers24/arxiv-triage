from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from arxiv_triage.models import reader as reader_models  # noqa: E402


def load_legacy_validator():
    spec = importlib.util.spec_from_file_location(
        "arxiv_triage_legacy_validate", ROOT / "scripts/validate.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_investigation_run_facade_is_additive_to_legacy_contracts() -> None:
    validator = load_legacy_validator()
    assert validator.SCHEMA_VERSION == "1.0"

    payload = {
        "schema_version": "2.0",
        "agent_run_id": "run-invalid",
        "validator_version": "investigation-contract-test",
        "checked_at": "2026-09-13T08:00:01Z",
        "input_hash": "a" * 64,
        "parsed_hash": None,
        "checks": [
            {
                "check_id": "schema",
                "status": "failed",
                "detail": "missing required field",
            }
        ],
        "errors": ["missing required field"],
        "referenced_hashes": [],
    }
    record = validator.validate_investigation_run_artifact(
        "validation", json.dumps(payload).encode("utf-8")
    )
    assert record.model_dump(mode="json") == payload


def test_investigation_reader_facade_uses_embedded_source_text(monkeypatch) -> None:
    validator = load_legacy_validator()
    expected = object()

    def validate(task, value):
        assert task == "task-with-source-text"
        assert value == b"raw reader output"
        return expected

    monkeypatch.setattr(reader_models, "validate_reader_output", validate)
    assert (
        validator.validate_investigation_reader_output(
            "task-with-source-text", b"raw reader output"
        )
        is expected
    )
