---
name: triage-topic
description: Runs one bounded, auditable arXiv investigation through deterministic workflow operations and role-specific workers
---

# Triage an arXiv topic

Use this skill only from the main orchestrator session. Follow
`docs/roles/orchestrator.md`; do not dispatch another orchestrator and do not
delegate beyond the one worker level.

## Preflight gate

The current investigation workflow is not runnable by assembling legacy
commands. Before starting, confirm that all command entry points and canonical
task/result validators named below exist and target the schema version declared
by the frozen inputs. In particular, do not dispatch the
paper screener until `ScreeningTask` and `ScreeningRecord` are defined and
validated, and do not dispatch any worker without a finalized validator.

If an entry point or contract is absent, stop before the affected dispatch,
preserve any already-created artifacts, and report that the workflow is not
implemented at that gate. Never substitute `scripts/fetch.py`,
`scripts/validate.py`, or `scripts/db.py` while they still implement legacy
schema `1.0` behavior.

The intended command surface is:

```text
uv run scripts/workflow.py create --spec <path> --profile <path> --search-plan <path>
uv run scripts/workflow.py status <investigation-id>
uv run scripts/fetch.py <investigation-id> <paper-id>
uv run scripts/workflow.py prepare-reader <investigation-id> <paper-id>
uv run scripts/workflow.py accept-run <agent-run-id>
uv run scripts/workflow.py prepare-critic <investigation-id> <paper-id>
uv run scripts/workflow.py prepare-reviewer <investigation-id>
uv run scripts/render.py <investigation-id>
uv run scripts/reconcile.py <investigation-id>
uv run scripts/db.py rebuild
```

Use these commands only after their implemented help and schema version match
the specification. Component discovery and screening entry points must be
named by the active component; the shared workflow must not invent them.

## Required inputs and bounds

Obtain before work begins:

- a non-empty arXiv query;
- paths to a schema-valid investigation spec, objective profile,
  and search plan;
- a positive candidate limit and screener batch-size limit;
- positive `max_concurrent_papers`, `max_concurrent_fetches`, and
  `max_concurrent_agents` values;
- provider-specific retrieval attempt and timeout bounds;
- the active component's reader focus, critic rubric, reviewer rubric, and
  exact skill hashes when supplied.

Do not invent component rules, workshop semantics, proposal semantics, or
rubric content. If a required choice is absent, obtain it before starting the
run. Record all limits in the frozen run configuration.

Maintain explicit counters for discovered candidates; screened decisions;
included, excluded, and membership-unresolved corpus entries; physical
attempts by logical job; and complete, analysis-unresolved, and failed included
papers. Never use an unbounded loop.

## Procedure

### 1. Validate and freeze inputs

Run the create operation with the exact spec, profile, and search-plan
paths. Let deterministic code validate structure and hashes and write the
frozen snapshots. Do not edit a snapshot after creation. Record the resulting
investigation ID and confirm `inputs_validated` with the status operation.

### 2. Discover and freeze the corpus

Invoke the active component's deterministic discovery operation with the exact
query, candidate limit, and search plan. It owns provider retrieval,
normalization, deduplication, stable paper identity, raw discovery records, and
hashing. Do not screen or deduplicate by judgment in the orchestrator.

Dispatch the paper screener only when its canonical task/result contract and
validator are implemented. Partition candidates into batches no larger than
the recorded batch limit. Preserve raw output and validation for every
physical attempt. Require exactly one validated decision per candidate across
the complete set; duplicates, omissions, or unknown candidates are contract
failures, not material for manual repair.

Map `selected` and `needs_review` to included membership and `screened_out` to
excluded membership. `membership_unresolved` is reserved for deterministic
discovery or identity failures. Freeze the complete deduplicated manifest and
verify:

```text
discovered = len(entries)
discovered = included + excluded + membership_unresolved
```

A processing cap may defer work visibly; it must not relabel a relevant or
ambiguous candidate as excluded.

### 3. Prepare sources for included papers

For included entries only, use the source-fetch operation through a pool
bounded by `max_concurrent_fetches` and `max_concurrent_papers`. Deterministic
code tries the documented exact-version source hierarchy and preserves raw
bytes, extraction reports, hashes, warnings, and fallback reasons.

Validate every `SourcePacket` and its normalized bytes before reader
preparation. An abstract-only fallback remains eligible but must stay visibly
degraded. A failed source chain reaches a visible included-paper `failed`
outcome; continue independent papers.

### 4. Dispatch and accept readers

Ask the workflow operation to prepare a `ReaderTask`; never construct one by
hand. Dispatch `.claude/agents/paper-reader.md` only after source files and
hashes verify and the task's embedded `source_text` matches the frozen source
hash. Bound total active workers by `max_concurrent_agents` and active paper
chains by `max_concurrent_papers`.

For every physical attempt:

1. allocate a unique run ID and attempt number;
2. freeze and hash its exact input;
3. append the start event;
4. dispatch once;
5. preserve the raw response or transport error;
6. invoke the single deterministic `validate_reader_output` gateway;
7. append the terminal lifecycle event and index the attempt;
8. promote a canonical `ReaderRecord` only after validation succeeds.

An output that reaches validation and fails ends that physical attempt as
`invalid`. A dispatch or transport failure without validatable output ends it
as `failed`. If the failure is transport, missing output, malformed JSON, or a
correctable schema error and attempt one was used, allocate one new physical
attempt with only the minimum deterministic correction errors. Never expose
hidden reasoning or the prior raw response. After attempt two, fail the logical
job visibly. Do not retry valid empty claims or other valid semantic results.

### 5. Dispatch and accept critics

After a canonical reader exists, ask the workflow to prepare a `CriticTask`
containing the same frozen `source_text`, source packet, and validated reader
record. Dispatch `.claude/agents/critic.md` under the same concurrency bounds
and persistence sequence.

Require exactly one verdict per reader claim and allow assessments to cite
only supported claims. Admit output only through `validate_critic_output`.
Apply the same maximum of two physical attempts and the same retryable
transport/schema classes. Do not retry `unsupported`, `overclaimed`,
evidence-classification mismatch, uncertain, or human-review outcomes. A valid
substantive objection produces `analysis_unresolved` or human review; it does
not trigger a reader reread or another critic pass. Otherwise accept
`complete`. Continue independent paper chains after any failure.

### 6. Close accounting and run one reviewer

Wait until every corpus entry has a final membership disposition and every
included entry is `complete`, `analysis_unresolved`, or `failed`. Recalculate:

```text
expected = CorpusManifest.counts.discovered
expected = included + excluded + membership_unresolved
included = complete + analysis_unresolved + failed
```

Run `prepare-reviewer`; deterministic guards must reject an open or mismatched
corpus. Dispatch exactly one logical reviewer job using
`.claude/agents/reviewer.md`. It may have attempt one plus one correction retry
only for the same transport/schema classes. It never receives mutable chat
history or hidden worker reasoning.

Admit output only through `validate_reviewer_output` and accept a validated
review without editing it. `ready` and
`ready_with_warnings` proceed to rendering. `blocked` transitions to
`review_blocked`; stop and do not render. An invalid review after its bounded
retry is a visible investigation contract failure.

### 7. Rank, render, and verify completion

Invoke the deterministic renderer only after an accepted non-blocking review.
Ranking uses the frozen objective and component score artifact and must not
compare results across different profile hashes. Require the report, table,
and human-review queue requested by the investigation.

Before completion, verify all seven corpus counts, all terminal states, every
artifact hash and path, exact claim-to-source resolution, critic coverage,
review evidence references, and visible degraded/failure/unresolved outcomes.
Then request `complete` or `complete_with_warnings` as determined by the
validated artifacts. Do not announce success if any required gate is open.

## Recovery

On restart, run the reconcile operation before new dispatch. Reconcile
canonical JSON and append-only trace events first, then rebuild or repair the
SQLite projection. Never infer evidence or overwrite an old attempt during
recovery. Resume only jobs that deterministic workflow guards report eligible,
with their remaining attempt counts intact.
