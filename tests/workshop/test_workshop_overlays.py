from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from arxiv_triage.models import CriticRubric, ReaderFocus, ReviewerRubric, sha256_json
from arxiv_triage.workshop import materialize_workshop_overlays


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / ".claude/skills/workshop-analysis"


def test_reviewed_workshop_overlays_are_task_ready_and_self_bound() -> None:
    manifest, focus, critic, reviewer = materialize_workshop_overlays(SKILL)
    assert manifest["skill_hash"] == sha256_json(
        {key: value for key, value in manifest.items() if key != "skill_hash"}
    )
    assert len(manifest["files"]) == 6
    assert len(focus.questions) == 8
    assert len(critic.checks) == 7
    assert len(reviewer.checks) == 8
    assert {
        focus.skill_hash,
        critic.skill_hash,
        reviewer.skill_hash,
    } == {manifest["skill_hash"]}


def test_overlay_cli_freezes_exact_task_inputs(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/workshop.py"),
            "--root",
            str(tmp_path),
            "materialize-overlays",
            "--workshop-id",
            "edge-cvpr-2026",
            "--skill-dir",
            str(SKILL),
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    focus = ReaderFocus.model_validate_json(
        (tmp_path / output["reader_focus_path"]).read_bytes()
    )
    critic = CriticRubric.model_validate_json(
        (tmp_path / output["critic_rubric_path"]).read_bytes()
    )
    reviewer = ReviewerRubric.model_validate_json(
        (tmp_path / output["reviewer_rubric_path"]).read_bytes()
    )
    assert focus.skill_hash == output["skill_hash"]
    assert critic.skill_hash == output["skill_hash"]
    assert reviewer.skill_hash == output["skill_hash"]
