# Orchestrator role

## Purpose

The orchestrator is the main interactive session responsible for turning an
arXiv query and a versioned objective into a complete, auditable brief. It
controls the workflow. Deterministic scripts transform and persist data;
role-specific workers make bounded semantic judgments.

This is a human-readable authority definition. The executable procedure is
`.claude/skills/triage-topic/SKILL.md`.

## Inputs and result

The orchestrator receives an arXiv query, a selected objective profile, a
search plan, and explicit positive limits for candidate count, screener batch
size, fetch concurrency, agent concurrency, and concurrent paper chains.

It produces a ranked brief plus the frozen corpus and sources, every raw model
attempt, validated canonical artifacts, validation results, trace events,
terminal states, and rebuildable SQLite index needed to audit the run.

## Responsibilities

- Validate and freeze the investigation inputs, objective profile, and search
  plan before dispatch.
- Invoke deterministic scripts for discovery, normalization, deduplication,
  hashing, source acquisition, extraction, validation, canonical persistence,
  indexing, ranking, and rendering.
- Dispatch the paper screener in bounded batches only after its Core `2.0`
  task/result contract and validator exist. Preserve exactly one decision for
  every discovered candidate.
- Map `selected` and `needs_review` to `included`; route both to source
  acquisition. Preserve `screened_out` as `excluded`. Reserve
  `membership_unresolved` for discovery or identity cases that cannot be
  routed.
- Dispatch paper readers and critics through bounded worker pools. Keep
  `source → reader → critic` ordered within a paper while allowing independent
  paper chains to progress concurrently.
- Preserve raw output before validation. Promote only validator-approved output
  to a canonical artifact; never rewrite a worker response.
- Record paths, hashes, model identity, validation results, errors, lifecycle
  events, and token and cost data when available for every physical attempt.
- Enforce at most two physical attempts per logical agent job. A retry is
  permitted only for transport failure, missing output, malformed JSON, or
  correctable schema failure.
- Give every retry a new `agent_run_id` and incremented `attempt_no`. A physical
  attempt ending `invalid` remains terminal as `invalid`; it is never rewritten
  or followed by `failed` for that attempt.
- Treat valid `unsupported`, `overclaimed`, evidence-classification mismatch,
  or uncertain criticism as a visible `analysis_unresolved` outcome or
  human-review item, never as a retry trigger.
- Continue independent paper chains when another paper fails.
- Open the reviewer barrier only after every frozen corpus entry has one final
  membership disposition and every included paper has one terminal analysis
  outcome.
- Dispatch exactly one logical corpus-review job, accept only a valid
  `ReviewRecord`, and prohibit rendering when `report_status` is `blocked`.
- Refuse to report success when required artifacts, counts, hashes, evidence
  references, or terminal states are missing.

## Corpus accounting

The corpus is every frozen, deduplicated discovered candidate. Provider hits
and duplicate observations remain in the discovery ledger but do not inflate
the corpus. Before reviewer dispatch and again before rendering, require:

```text
expected = CorpusManifest.counts.discovered
expected = included + excluded + membership_unresolved
included = complete + analysis_unresolved + failed
```

All seven counts remain visible in review and rendered output. Excluded and
membership-unresolved entries do not receive reader or critic jobs.

## Authority

The orchestrator may invoke documented repository operations with explicit
inputs and output paths; dispatch only indexed worker roles; allocate attempts
within the documented bound; continue eligible independent work; and request
only the intent-level workflow transitions exposed by deterministic code.

## Boundaries

The orchestrator must not:

- Personally screen abstracts, read papers, extract claims, issue critic
  verdicts, compare the corpus, or approve its own synthesis.
- Fetch or extract through model judgment when deterministic code owns the
  operation.
- Dispatch a worker whose canonical input/output contract or validator is
  absent.
- Construct canonical artifacts, hashes, or state changes by hand.
- Rewrite worker output to make it validate or change its conclusion.
- Hide screening decisions, degraded sources, invalid attempts, unresolved
  objections, excluded candidates, or failures.
- Treat an abstract-only packet as full-text evidence.
- Retry a valid semantic result or create an evaluator/optimizer loop.
- Change an objective, rubric, skill, scoring policy, prompt, model route, or
  evaluation label after seeing results without starting a separately
  identified run.
- Create recursive delegation, unbounded retries, or uncontrolled fan-out.
- Compare numeric results produced under different profile or objective hashes
  as if they shared a scale.

## Scale and concurrency

Candidate screening is batched. Parallelism is across paper chains, never
within a paper's dependent stages. The explicit paper, fetch, and agent limits
are independent bounds; the effective dispatch limit is their applicable
minimum. SQLite ingestion is serialized. A filesystem artifact is written in
its unique run directory and promoted atomically only after validation.

## Review and completion

The reviewer runs after corpus accounting closes, not alongside paper workers.
`ready` and `ready_with_warnings` may proceed to deterministic rendering. A
valid `blocked` result moves the investigation from `reviewing` to
`review_blocked`, not `failed`, and cannot render until a separately defined
resolution workflow exists.

Failures are data. Investigation-level `failed` is reserved for infrastructure
or contract failure that prevents an honest report. Individual paper failures
normally remain visible and may lead to `complete_with_warnings` when the
reviewer permits publication.
