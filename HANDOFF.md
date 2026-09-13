# arxiv-triage investigation-platform handoff

Updated: 2026-09-13

## Read first

1. `docs/README.md`
2. `AGENTS.md`
3. `docs/schema.md`
4. `docs/decisions.md`
5. `docs/specs/01-core-investigation-platform.md`
6. `docs/reviews/investigation-implementation-review.md`

Repository documentation is authoritative. Escalate uncertain core design
decisions instead of silently choosing. Deterministic work belongs in code;
paper reading, criticism, screening, and corpus review belong to bounded
workers.

## Product direction

The project is becoming an objective-driven personal research tool rather than
a Micron-specific triage system. The shared investigation platform supports
future workshop-analysis and proposal-relevance components. Open-ended latest-
developments analysis remains deferred.

The execution topology is:

```text
frozen source -> reader -> canonical ReaderRecord -> critic -> terminal paper
                                                               |
all terminal paper chains + all reader/critic records ----------+
                                                               v
                                                        corpus reviewer
```

Paper chains may run concurrently. A paper's reader and critic remain ordered,
and the reviewer runs once after corpus accounting closes. Workers never invoke
one another.

## Approved behavior

The orchestrator, paper-reader, critic, reviewer, paper-screener, and triage
runbook definitions have been human-reviewed and approved with the current
working-tree edits. Future semantic changes still require a clear review diff.

Agent behavior follows the active supplied contract rather than a branded
workflow version. Serialized artifacts retain `schema_version` so incompatible
records can be rejected. Prompts copy that value from the frozen task.

The reader extracts a bounded problem, method, claims, and warnings from one
frozen source. The critic checks only the supplied reader record against the
same source and makes only profile-declared assessments. The reviewer compares
the closed corpus and challenges synthesis or report readiness without editing
underlying artifacts.

The paper-screener behavior is described but remains ineligible for dispatch
until exact `ScreeningTask` and `ScreeningRecord` contracts and deterministic
validation exist.

## Implemented foundation

`src/arxiv_triage/models/` contains exact investigation, objective, search,
corpus, paper, source, reader, critic, reviewer, agent-run, validation, outcome,
and trace contracts. Reader and critic tasks embed the exact hash-bound source
text supplied to tool-free workers.

`src/arxiv_triage/workflow/` contains lifecycle states, transition guards,
retry eligibility, uniqueness rules, concurrency bounds, reviewer barriers,
and crash-recovery classifications.

`src/arxiv_triage/storage/` contains immutable artifact writes, lifecycle trace
JSONL, the rebuildable SQLite projection, and reconciliation primitives.

`scripts/validate.py` retains legacy behavior and exposes additive,
version-neutral investigation validation facades:

- `validate_investigation_reader_output`
- `validate_investigation_critic_output`
- `validate_investigation_reviewer_output`
- `validate_investigation_run_artifact`

The concrete schema discriminator remains version `2.0`; it is a compatibility
field, not a product or workflow name.

## Approved lifecycle and persistence decisions

- Canonical JSON artifacts and trace events are authoritative; SQLite is a
  rebuildable index.
- The new index uses caller-selected `data/triage-v2.db`. The legacy database is
  not migrated or silently reused.
- `invalid` is terminal for one physical attempt. A permitted correction retry
  receives a new run ID and incremented attempt number.
- A blocked review enters `review_blocked`, not infrastructure `failed`.
- Frozen corpus membership is `included`, `excluded`, or
  `membership_unresolved`.
- Only included papers are analyzed, with outcomes `complete`,
  `analysis_unresolved`, or `failed`.
- Reviewer accounting preserves all seven corpus counts and validates both
  membership and analysis equations.

## Verification

The network-free test suite is:

```bash
PYTHONPATH=src uv run --with pytest pytest tests -q
```

Most recent result before this handoff update:

```text
88 passed, 7 subtests passed
```

## Next phase

Phase 1 provides contracts, workflow guards, persistence primitives, worker
definitions, and tests. It does not yet provide the executable investigation
pipeline.

Next implementation order:

1. Define exact `ScreeningTask` and `ScreeningRecord` contracts.
2. Add the screening validation gateway and contract fixtures.
3. Implement the investigation workflow CLI and task preparation/acceptance.
4. Implement deterministic source acquisition and normalization.
5. Implement deterministic ranking, report rendering, database rebuild, and
   reconciliation command entry points.
6. Run the synthetic three-paper end-to-end acceptance investigation.
7. Begin the workshop-analysis vertical slice.

Do not begin Tavily integration, proposal search, proposal generation, latest-
developments analysis, a vector store, UI, or workflow framework during the
shared pipeline phase.

## Repository hygiene

Tracked `.DS_Store` files remain present. Do not remove them silently; cleanup
is a separate change.
