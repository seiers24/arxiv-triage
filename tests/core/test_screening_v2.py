from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest
from pydantic import ValidationError

from arxiv_triage.models import (
    AgentRun,
    CandidatePaper,
    CandidateSet,
    CorpusManifest,
    InvestigationSpec,
    ObjectiveProfile,
    ScreeningRecord,
    ScreeningScope,
    ScreeningTask,
    SearchPlan,
    sha256_json,
    validate_screening_output,
)
from arxiv_triage.workflow import (
    FailureKind,
    GuardViolation,
    InvestigationState,
    JobAttempt,
    JobType,
    LogicalJobKey,
    WorkflowService,
    next_attempt,
    partition_candidates,
    prepare_screening_task,
    route_authoritative_membership,
    route_screening_records,
)


HASH = "a" * 64


def self_hash(payload: dict[str, object], field: str) -> dict[str, object]:
    payload.pop(field, None)
    payload[field] = sha256_json(payload)
    return payload


def objective() -> ObjectiveProfile:
    return ObjectiveProfile.model_validate(
        self_hash(
            {
                "schema_version": "2.0",
                "profile_id": "profile-screening-test",
                "component": "workshop-analysis",
                "origin": "user_authored",
                "criteria": [
                    {
                        "criterion_id": "relevance",
                        "definition": "Relevance to the objective",
                        "score_type": "integer_0_5",
                        "weight": 1,
                        "gate": False,
                        "anchors": {"0": "Absent", "5": "Direct"},
                    }
                ],
                "human_review_triggers": [],
            },
            "profile_hash",
        )
    )


def scope() -> ScreeningScope:
    return ScreeningScope.model_validate(
        self_hash(
            {
                "schema_version": "2.0",
                "question": "Which papers study memory systems?",
                "inclusion_rules": ["Studies memory-system behavior"],
                "exclusion_rules": ["Editorial material only"],
            },
            "scope_hash",
        )
    )


def candidate(number: int, *, abstract: str | None = "We evaluate 42 systems.") -> CandidatePaper:
    identity = self_hash(
        {
            "schema_version": "2.0",
            "paper_id": f"paper-{number}",
            "title": f"Chip α architecture {number}",
            "authors": ["A. Author"],
            "published": None,
            "identifiers": [
                {
                    "scheme": "arxiv",
                    "value": f"2609.{number:05d}v1",
                    "url": f"https://arxiv.org/abs/2609.{number:05d}",
                }
            ],
            "identity_status": "resolved_exact",
        },
        "identity_hash",
    )
    return CandidatePaper.model_validate(
        self_hash(
            {
                "schema_version": "2.0",
                "paper_identity": identity,
                "abstract": abstract,
                "discovery_refs": [f"discovery-{number}"],
            },
            "candidate_hash",
        )
    )


def candidate_set(count: int = 3) -> CandidateSet:
    candidates = [candidate(number, abstract=None if number == 2 else "We evaluate 42 systems.") for number in range(1, count + 1)]
    return CandidateSet.model_validate(
        self_hash(
            {
                "schema_version": "2.0",
                "investigation_id": "inv-screening-test",
                "search_plan_hash": "b" * 64,
                "discovery_ledger_hash": "c" * 64,
                "frozen_at": "2026-09-13T20:00:00Z",
                "candidates": [item.model_dump(mode="json") for item in candidates],
            },
            "candidate_set_hash",
        )
    )


def task_for(candidates: CandidateSet, ordinal: int, size: int = 2) -> ScreeningTask:
    return prepare_screening_task(
        candidate_set=candidates,
        objective_profile=objective(),
        screening_scope=scope(),
        batch_ordinal=ordinal,
        batch_size_limit=size,
        agent_run_id=f"run-screening-{ordinal}",
    )


def record_payload(task: ScreeningTask) -> dict[str, object]:
    decisions = []
    states = ("selected", "needs_review", "screened_out")
    for index, item in enumerate(task.candidates):
        title = item.paper_identity.title
        quote = "Chip α"
        decisions.append(
            {
                "paper_id": item.paper_identity.paper_id,
                "candidate_hash": item.candidate_hash,
                "state": states[(task.batch_ordinal + index - 1) % len(states)],
                "reason": "Decision bounded to supplied title and scope",
                "evidence_spans": [
                    {
                        "field": "title",
                        "start_char": title.index(quote),
                        "end_char": title.index(quote) + len(quote),
                        "quote": quote,
                    }
                ],
            }
        )
    return {
        "schema_version": "2.0",
        "role": "paper_screener",
        "job_type": "paper_screen",
        "agent_run_id": task.agent_run_id,
        "investigation_id": task.investigation_id,
        "screening_batch_id": task.screening_batch_id,
        "candidate_set_hash": task.candidate_set_hash,
        "objective_profile_hash": task.objective_profile.profile_hash,
        "screening_scope_hash": task.screening_scope.scope_hash,
        "input_hash": task.input_hash,
        "decisions": decisions,
    }


def test_contracts_are_closed_hash_bound_and_allow_title_only_candidates() -> None:
    candidates = candidate_set()
    assert candidates.candidates[1].abstract is None
    payload = candidates.model_dump(mode="json")
    payload["unexpected"] = True
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CandidateSet.model_validate(payload)

    changed = candidates.model_dump(mode="json")
    changed["candidates"][0]["abstract"] = "Mutated after freeze"
    with pytest.raises(ValidationError, match="candidate_hash"):
        CandidateSet.model_validate(changed)


def test_gateway_accepts_exact_ordered_output_and_unicode_offsets() -> None:
    task = task_for(candidate_set(), 1)
    record = validate_screening_output(task, record_payload(task))
    assert [item.paper_id for item in record.decisions] == [
        item.paper_identity.paper_id for item in task.candidates
    ]


def test_gateway_accepts_abstract_spans_and_raw_json_bytes() -> None:
    candidates = candidate_set(1)
    task = task_for(candidates, 1)
    payload = record_payload(task)
    abstract = task.candidates[0].abstract
    assert abstract is not None
    quote = "42 systems"
    payload["decisions"][0]["evidence_spans"] = [
        {
            "field": "abstract",
            "start_char": abstract.index(quote),
            "end_char": abstract.index(quote) + len(quote),
            "quote": quote,
        }
    ]
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    assert validate_screening_output(task, encoded).decisions[0].paper_id == "paper-1"
    with pytest.raises(ValidationError):
        validate_screening_output(task, b"not-json")


def test_screening_output_rejects_unknown_fields() -> None:
    task = task_for(candidate_set(1), 1)
    payload = record_payload(task)
    payload["decisions"][0]["unexpected"] = True
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        validate_screening_output(task, payload)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "foreign", "reordered", "substituted"])
def test_gateway_atomically_rejects_bad_candidate_coverage(mutation: str) -> None:
    task = task_for(candidate_set(), 1)
    payload = record_payload(task)
    decisions = payload["decisions"]
    assert isinstance(decisions, list)
    if mutation == "missing":
        decisions.pop()
    elif mutation == "duplicate":
        decisions[1] = deepcopy(decisions[0])
    elif mutation == "foreign":
        decisions[1]["paper_id"] = "paper-foreign"
    elif mutation == "substituted":
        decisions[1]["candidate_hash"] = HASH
    else:
        decisions.reverse()
    with pytest.raises((ValidationError, ValueError)):
        validate_screening_output(task, payload)


def test_gateway_rejects_inexact_and_null_abstract_evidence() -> None:
    task = task_for(candidate_set(), 1)
    inexact = record_payload(task)
    inexact["decisions"][0]["evidence_spans"][0]["quote"] = "Chip"
    with pytest.raises(ValueError, match="does not reconstruct"):
        validate_screening_output(task, inexact)

    null_abstract = record_payload(task)
    null_abstract["decisions"][1]["evidence_spans"] = [
        {"field": "abstract", "start_char": 0, "end_char": 1, "quote": "X"}
    ]
    with pytest.raises(ValueError, match="abstract is null"):
        validate_screening_output(task, null_abstract)


@pytest.mark.parametrize(
    "field",
    [
        "agent_run_id",
        "investigation_id",
        "screening_batch_id",
        "candidate_set_hash",
        "objective_profile_hash",
        "screening_scope_hash",
        "input_hash",
    ],
)
def test_gateway_rejects_every_cross_input_binding_mismatch(field: str) -> None:
    task = task_for(candidate_set(), 1)
    payload = record_payload(task)
    payload[field] = HASH if field.endswith("hash") else "wrong-binding"
    with pytest.raises(ValueError, match=f"{field} does not match task"):
        validate_screening_output(task, payload)


def test_partition_and_task_preparation_are_bounded_ordered_and_stable() -> None:
    candidates = candidate_set(5)
    batches = partition_candidates(candidates.candidates, 2)
    assert [len(batch) for batch in batches] == [2, 2, 1]
    assert [item.paper_identity.paper_id for batch in batches for item in batch] == [
        f"paper-{number}" for number in range(1, 6)
    ]
    first = task_for(candidates, 1)
    repeated = task_for(candidates, 1)
    assert first.screening_batch_id == repeated.screening_batch_id == "screening-batch-0001"
    assert first.input_hash == repeated.input_hash
    with pytest.raises(GuardViolation, match="non-empty"):
        task_for(candidates, 4)
    with pytest.raises(GuardViolation, match="positive integer"):
        partition_candidates(candidates.candidates, True)


def test_global_coverage_routes_all_states_and_identity_override_in_frozen_order() -> None:
    candidates = candidate_set()
    task_1 = task_for(candidates, 1)
    task_2 = task_for(candidates, 2)
    task_2_payload = record_payload(task_2)
    task_2_payload["decisions"][0]["state"] = "screened_out"
    records = [
        validate_screening_output(task_2, task_2_payload),
        validate_screening_output(task_1, record_payload(task_1)),
    ]
    routes = route_screening_records(
        candidate_set=candidates,
        objective_profile=objective(),
        screening_scope=scope(),
        records=records,
        identity_failure_paper_ids=["paper-2"],
    )
    assert [route.paper_id for route in routes] == ["paper-1", "paper-2", "paper-3"]
    assert [route.membership_status for route in routes] == [
        "included",
        "membership_unresolved",
        "excluded",
    ]


def test_global_coverage_rejects_partial_duplicate_and_wrong_scope() -> None:
    candidates = candidate_set()
    task_1 = task_for(candidates, 1)
    record_1 = validate_screening_output(task_1, record_payload(task_1))
    kwargs = {
        "candidate_set": candidates,
        "objective_profile": objective(),
        "screening_scope": scope(),
    }
    with pytest.raises(GuardViolation, match="cover every"):
        route_screening_records(records=[record_1], **kwargs)
    with pytest.raises(GuardViolation, match="batch IDs"):
        route_screening_records(records=[record_1, record_1], **kwargs)

    task_2 = task_for(candidates, 2)
    wrong = record_payload(task_2)
    wrong["screening_scope_hash"] = HASH
    wrong_record = ScreeningRecord.model_validate(wrong)
    with pytest.raises(GuardViolation, match="objective, and scope"):
        route_screening_records(records=[record_1, wrong_record], **kwargs)


def test_zero_candidate_and_authoritative_paths_are_explicit() -> None:
    empty = candidate_set(0)
    assert partition_candidates(empty.candidates, 10) == ()
    assert route_screening_records(
        candidate_set=empty,
        objective_profile=objective(),
        screening_scope=scope(),
        records=[],
    ) == ()
    with pytest.raises(GuardViolation, match="explicit"):
        route_authoritative_membership(
            candidate_set=candidate_set(), authoritative_membership=False
        )
    routes = route_authoritative_membership(
        candidate_set=candidate_set(), authoritative_membership=True
    )
    assert all(route.membership_status == "included" for route in routes)


def test_screening_lifecycle_requires_completed_discovery_and_coverage() -> None:
    with pytest.raises(GuardViolation, match="completion rule"):
        WorkflowService.freeze_candidates(
            InvestigationState.DISCOVERING,
            search_completion_satisfied=False,
            candidate_set_valid=True,
        )
    frozen = WorkflowService.freeze_candidates(
        InvestigationState.DISCOVERING,
        search_completion_satisfied=True,
        candidate_set_valid=True,
    )
    screening = WorkflowService.begin_screening(frozen)
    with pytest.raises(GuardViolation, match="complete screening"):
        WorkflowService.freeze_screened_corpus(
            screening,
            screening_coverage_valid=False,
            membership_valid=True,
            counts_valid=True,
        )
    assert WorkflowService.freeze_screened_corpus(
        screening,
        screening_coverage_valid=True,
        membership_valid=True,
        counts_valid=True,
    ) is InvestigationState.CORPUS_FROZEN
    assert WorkflowService.freeze_authoritative_corpus(
        frozen,
        authoritative_membership=True,
        membership_valid=True,
        counts_valid=True,
    ) is InvestigationState.CORPUS_FROZEN


def test_screening_logical_job_uses_batch_identity_and_bounded_retries() -> None:
    key = LogicalJobKey(
        "inv-screening-test", JobType.PAPER_SCREEN, None, "screening-batch-0001"
    )
    retry = next_attempt(
        key=key,
        prior_attempts=(JobAttempt(key, 1),),
        failure_kind=FailureKind.SCHEMA_VALIDATION,
        canonical_exists=False,
    )
    assert retry.eligible and retry.next_attempt_no == 2
    exhausted = next_attempt(
        key=key,
        prior_attempts=(JobAttempt(key, 1), JobAttempt(key, 2)),
        failure_kind=FailureKind.MALFORMED_JSON,
        canonical_exists=False,
    )
    assert not exhausted.eligible
    with pytest.raises(GuardViolation, match="screening_batch_id"):
        LogicalJobKey("inv-screening-test", JobType.PAPER_SCREEN, None)


def test_agent_run_enforces_exclusive_screening_scope() -> None:
    payload = {
        "schema_version": "2.0",
        "agent_run_id": "run-screening-1",
        "investigation_id": "inv-screening-test",
        "paper_id": None,
        "screening_batch_id": "screening-batch-0001",
        "role": "paper_screener",
        "job_type": "paper_screen",
        "attempt_no": 1,
        "status": "failed",
        "model": "model-test",
        "agent_definition_hash": HASH,
        "component_skill_hash": None,
        "objective_profile_hash": objective().profile_hash,
        "input_path": "data/investigations/inv-screening-test/runs/run-screening-1/input.json",
        "input_hash": HASH,
        "raw_output_path": None,
        "raw_output_hash": None,
        "validation_path": None,
        "validation_hash": None,
        "canonical_path": None,
        "canonical_hash": None,
        "started_at": "2026-09-13T20:00:00Z",
        "completed_at": "2026-09-13T20:00:01Z",
        "duration_ms": 1000,
        "tokens_in": None,
        "tokens_out": None,
        "cost_usd": None,
        "error": "transport failed",
    }
    assert AgentRun.model_validate(payload).screening_batch_id == "screening-batch-0001"
    with pytest.raises(ValidationError, match="null paper_id"):
        AgentRun.model_validate(dict(payload, paper_id="paper-1"))


def test_workflow_cli_freezes_screens_and_routes_a_complete_candidate_set(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    profile = objective()
    plan = SearchPlan.model_validate(
        self_hash(
            {
                "schema_version": "2.0",
                "search_plan_id": "search-screening-test",
                "component": profile.component,
                "providers": [],
                "inclusion_rules": ["fixture"],
                "exclusion_rules": [],
                "completion_rule": {"kind": "fixture_exhausted"},
                "budget": {"fixture": True},
            },
            "search_plan_hash",
        )
    )
    spec = InvestigationSpec.model_validate(
        self_hash(
            {
                "schema_version": "2.0",
                "investigation_id": "inv-screening-test",
                "kind": "fixture",
                "question": "Which fixture papers are in scope?",
                "scope": {},
                "requested_outputs": ["report", "papers_csv"],
                "uncertainty_policy": "escalate",
                "created_at": "2026-09-13T20:00:00Z",
            },
            "spec_hash",
        )
    )
    candidates_payload = candidate_set().model_dump(mode="json")
    candidates_payload["search_plan_hash"] = plan.search_plan_hash
    candidates_payload["candidate_set_hash"] = sha256_json(
        {
            key: value
            for key, value in candidates_payload.items()
            if key != "candidate_set_hash"
        }
    )
    candidates = CandidateSet.model_validate(candidates_payload)

    inputs = tmp_path / "inputs"
    inputs.mkdir()
    paths = {
        "spec": inputs / "spec.json",
        "profile": inputs / "profile.json",
        "plan": inputs / "plan.json",
        "candidates": inputs / "candidates.json",
        "scope": inputs / "scope.json",
    }
    values = {
        "spec": spec,
        "profile": profile,
        "plan": plan,
        "candidates": candidates,
        "scope": scope(),
    }
    for key, path in paths.items():
        path.write_text(values[key].model_dump_json(), encoding="utf-8")

    def run(*arguments: str) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [
                sys.executable,
                str(repository_root / "scripts/workflow.py"),
                "--root",
                str(tmp_path),
                *arguments,
            ],
            check=False,
            text=True,
            capture_output=True,
        )
        assert result.returncode == 0, result.stderr
        return result

    run(
        "create",
        "--spec",
        str(paths["spec"]),
        "--profile",
        str(paths["profile"]),
        "--search-plan",
        str(paths["plan"]),
    )
    run(
        "freeze-candidates",
        "inv-screening-test",
        "--candidate-set",
        str(paths["candidates"]),
        "--screening-scope",
        str(paths["scope"]),
        "--search-complete",
    )
    prepared = json.loads(
        run(
            "prepare-screening",
            "inv-screening-test",
            "--batch-size",
            "2",
        ).stdout
    )
    assert prepared["batches"] == 2
    for relative_task_path in prepared["task_paths"]:
        task_path = tmp_path / relative_task_path
        task = ScreeningTask.model_validate_json(task_path.read_bytes())
        raw_path = inputs / f"{task.agent_run_id}-output.json"
        raw_path.write_text(json.dumps(record_payload(task)), encoding="utf-8")
        run(
            "accept-run",
            "--task",
            str(task_path),
            "--raw-output",
            str(raw_path),
            "--model",
            "fixture-model",
            "--agent-definition",
            str(repository_root / ".claude/agents/paper-screener.md"),
        )
    run(
        "freeze-corpus",
        "inv-screening-test",
        "--mode",
        "semantic",
        "--frozen-at",
        "2026-09-13T20:05:00Z",
    )
    manifest = CorpusManifest.model_validate_json(
        (tmp_path / "data/investigations/inv-screening-test/corpus.json").read_bytes()
    )
    assert manifest.counts.discovered == 3
    assert manifest.counts.included == 3
    assert len(list((tmp_path / "logs").glob("trace.jsonl"))) == 1
