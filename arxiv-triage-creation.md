# arxiv-triage: eight-hour creation plan

## Purpose

Build and demonstrate one small, complete, defensible agentic research workflow within the next 24 hours.

The finished proof of concept should take one arXiv query, fetch a bounded set of recent papers, use a paper-reader and an independent critic to assess them, and produce a deterministic ranked brief for datacenter memory and AI infrastructure. Every claim must be traceable to an arXiv ID and source span. Failed and unresolved papers must remain visible.

This is preparation for an unknown research assignment, not an attempt to reproduce Micron's internal platform. The internship description is context for prioritization, not a requirement to implement every listed technology.

## The result to aim for

At the end of eight hours, be able to run and explain this flow:

```text
query
  -> deterministic arXiv fetch and stable selection of 10-15 papers
  -> frozen paper records with arXiv IDs, abstracts, metadata, and hashes
  -> parallel paper-reader calls, one independent call per paper
  -> deterministic schema and exact-source-span validation
  -> parallel critic calls, one per valid reader record
  -> one bounded re-read when a critic rejects or qualifies a claim
  -> deterministic ranking, gates, and tie-breaking
  -> out/brief.md plus inspectable artifacts, trace events, and a SQLite index
```

The output should normally show the top 10, but it must never silently fill ten slots by hiding failures. The brief begins with fetched, completed, unresolved, and failed counts.

## Scope: what ships and what does not

### Must ship

- A working end-to-end run on at least 5 papers; target 10-15 if runtime and model access allow.
- One orchestrator and two worker roles: `paper-reader` and `critic`.
- Parallel execution across papers, with a conservative concurrency limit such as 4.
- Structured reader and critic outputs with deterministic validation.
- Exact abstract spans for paper-stated claims.
- Explicit separation between a paper-stated claim and the workflow's Micron-oriented inference.
- One critic pass and at most one reader retry; thereafter the paper is `unresolved`.
- Deterministic ranking and tie-breaking.
- Visible failure counts and no silently dropped paper.
- Traceable input, prompt/agent version, model, output path, hashes, validation result, and retry count.
- Tests for the most important deterministic behavior.
- A README quickstart that has been executed exactly as written.

### Stretch only after the complete run works

- A run manifest or immutable paper-packet directory beyond the metadata already stored.
- A small reader-only versus reader-plus-critic comparison on 3-5 frozen papers.
- A sanitized example run checked into an `examples/` directory.
- A five-dimension ranking rubric from `assessment_on_agentic_infa.md` if the simpler current scoring contract has already proved stable.

### Explicitly out of scope

- Full-PDF extraction, page citations, OCR, or table parsing.
- A dashboard or other UI.
- Vector databases, RAG, knowledge graphs, or cross-run memory.
- Cloud deployment, containers, Kubernetes, RBAC, or CI/CD.
- LangGraph, AutoGen, or another orchestration framework.
- Agent voting, a third worker role, recursive delegation, or an autonomous swarm.
- Actual architectural simulation. The reader may propose a testable extension or simulation plan, clearly labeled as an inference, but the system does not claim to validate it.
- A 20-30-paper golden set. Document how it would be built; do not spend this sprint building it.

These omissions are strengths when explained correctly: the control flow is known in advance, so a fixed workflow is easier to inspect, test, and defend than framework machinery or open-ended autonomy.

## Architecture decisions to lock before coding

The repository currently has documentation drift. Resolve it once in `docs/` and make other files link to the canonical decision.

1. **Artifacts are the evidence source of truth.** Reader and critic JSON files retain exactly what each model produced.
2. **`scripts/validate.py` owns contract validation.** `scripts/db.py` may call the same validation functions, but persistence must not define a second schema.
3. **`logs/trace.jsonl` is the append-only execution ledger.** It records one event per dispatch or failed attempt.
4. **SQLite is a queryable, rebuildable index.** It stores validated runs, claims, scores, verdicts, artifact paths, and hashes. It is not hidden workflow state.
5. **The orchestrator controls; workers judge.** The orchestrator dispatches, validates, routes a bounded retry, and invokes deterministic tools. It does not silently rewrite worker conclusions.
6. **The critic is isolated.** It receives the frozen paper source and reader artifact, but not hidden reasoning, preliminary rank, other critics' opinions, or a desired conclusion.
7. **Reproducibility means reconstructability, not identical model prose.** Frozen inputs, hashes, prompt versions, model IDs, and deterministic code make a run auditable. LLM output may still vary on replay.

Use a small public strategic lens rather than implying knowledge of confidential Micron strategy:

- DRAM, NAND, HBM, SSDs, and memory hierarchy.
- CXL, disaggregated memory, packaging, chiplets, and interconnect.
- Processing-in-memory and near-memory computing.
- Bandwidth, capacity, latency, energy, thermal, endurance, and reliability limits.
- AI training or inference changes that alter memory-system demand.

## Minimal data contract

Keep the contract small enough to explain from memory. Extend the existing reader artifact only where the distinction between source fact and analyst judgment would otherwise be ambiguous.

### Reader record

- Identity: `role`, exact `arxiv_id`, and input hash.
- Summary: problem and method, each concise.
- Paper claims: text, exact `source_span` or `null`, evidence type, and provenance.
- Strategic relevance: score, one-sentence reason, public lens category, linked claim indices, and assumptions.
- Importance score and whether there is a concrete extension path.
- Optional extension proposal: hypothesis, smallest useful experiment, comparison baseline, and success metric. Label this as analyst inference.

### Critic record

- Identity: `role`, `arxiv_id`, and exact `reader_run_id`.
- One verdict for every reader claim: `supported`, `unsupported`, or `overclaimed`, with a concise reason.
- A verdict on whether the strategic relevance chain is justified by the linked claims.
- No rewritten reader record and no new overall rank.

### Deterministic invariants

- A claim with `source_span: null` cannot be `supported`.
- A non-null source span must occur exactly in the frozen abstract after documented whitespace normalization.
- A critic must return exactly one verdict for every claim index—no missing or duplicate indices.
- The critic's arXiv ID and reader run ID must match the inputs.
- Enum values and score ranges must match `docs/schema.md` exactly.
- Every fetched paper must finish as `complete`, `unresolved`, or `failed` before a run can be reported as successful.

Do not redesign the entire existing database during this sprint. Add only the fields needed to preserve these contracts, or retain new fields in the JSON artifact when they are not required for querying.

## The eight-hour schedule

The time boxes include coding, tests, and documentation. Stop at each gate and preserve a working state before moving on.

### 0:00-0:40 — freeze the contract and remove contradictions

Work:

- Fill in `docs/schema.md` with the reader and critic contracts and invariants.
- Record the artifact/JSONL/SQLite responsibilities in `docs/decisions.md`, including the rejected simpler alternative.
- Put a compact evaluation rubric and limitations in `docs/evaluation.md`.
- Update `README.md` wording only where it contradicts those documents.
- Decide the initial ranking rule now; do not tune it after seeing the demo results.

Gate: you can describe what every persisted file or row means, and `AGENTS.md`, `README.md`, `HANDOFF.md`, and `docs/` no longer disagree about validation or tracing.

### 0:40-1:35 — build deterministic fetch and frozen inputs

Work:

- Implement `scripts/fetch.py` using the existing arXiv dependency.
- Accept query, result limit, and output path arguments.
- Normalize versioned IDs, deduplicate deterministically, and sort stably.
- Persist the exact metadata and abstract used by downstream workers.
- Compute an input hash from canonical JSON.
- Insert or upsert paper metadata through deterministic code; agents never fetch.
- Add a cached fixture so fetch parsing can be tested without network access.

Gate: one command produces a stable `data/papers.json`, and rerunning it on the same fixture produces the same order and hashes.

### 1:35-2:25 — centralize validation and test failure behavior

Work:

- Implement `scripts/validate.py` with the canonical models and reusable validation functions.
- Make `scripts/db.py` consume those functions instead of maintaining a competing contract where feasible.
- Enforce exact source spans, claim/verdict coverage, enums, ranges, identity matching, and null-span rules.
- Preserve invalid artifacts and their error message; never partially ingest them.
- Use a one-retry limit encoded in the runbook, not an unbounded loop.
- Add focused tests for valid input, malformed JSON, invalid enum, bad span, missing verdict, duplicate verdict, and transaction rollback.

Gate: intentional bad records fail loudly and leave no partial database state.

### 2:25-3:35 — finish the two worker prompts and fixed runbook

Work:

- Complete `.claude/agents/paper-reader.md` so it reads only the supplied paper record and emits only the schema artifact.
- Add `.claude/agents/critic.md` with independent, adversarial checks and complete per-claim verdict coverage.
- Add `.claude/skills/triage-topic/SKILL.md` as the orchestrator's executable checklist.
- In the runbook, dispatch readers concurrently across papers, validate all results, then dispatch critics concurrently for valid records.
- Keep each paper's chain sequential: reader -> validation -> critic -> decision.
- Route an invalid reader response to one schema-correction retry. Route a rejected or overclaimed result to one source-bound re-read. After that, mark it unresolved.
- Append a trace event for every attempt, including failed validation.

Gate: on a supplied paper fixture, both roles return ingestible artifacts without manual repair.

This demonstrates four agentic patterns without inventing extra agents:

- **Prompt chaining:** reader output becomes critic input, then validated judgments become ranker input.
- **Parallelization:** independent papers are read and criticized concurrently.
- **Orchestrator-workers:** the orchestrator owns task assignment and aggregation; role-specific workers own bounded judgments.
- **Evaluator-optimizer with a hard bound:** the critic evaluates; one re-read may improve the record; the loop then terminates visibly.

### 3:35-4:30 — implement deterministic ranking and report generation

Work:

- Implement `scripts/rank.py` over validated records and verdicts.
- Use the score rule committed in hour one.
- Apply a gate: a rejected load-bearing claim or unresolved relevance chain becomes `needs_review`, regardless of numeric score.
- Define stable tie-breakers, ending with arXiv ID ascending.
- Write `out/brief.md` with counts at the top, a ranked table, evidence-backed claim summaries, strategic relevance, extension proposal, and unresolved/failed sections.
- Ensure every displayed claim includes its arXiv ID and verdict.
- Refuse to call the run successful if a fetched paper has no terminal state.
- Add tests for formula boundaries, gates, ties, and missing-paper detection.

Gate: the ranker can build the same report twice from frozen artifacts without a model call, with byte-identical ranking and counts.

### 4:30-5:05 — finish the audit trail

Work:

- Ensure every dispatch or attempt has a trace line with paper ID, role, timestamp, model, prompt/agent hash, input hash, artifact path/hash, validation result, retry count, and verdict summary when available.
- Confirm SQLite rows point to the same artifacts and hashes.
- Make duplicate artifact ingestion idempotent.
- Add one command or documented query that reconstructs the run summary from stored state.

Gate: choose any claim in the brief and trace it back to the exact abstract, reader artifact, critic verdict, agent definition version, and run attempt.

### 5:05-6:15 — run a three-paper smoke test and fix the pipeline

Use a deliberately mixed set:

- One clearly memory-system-relevant paper.
- One adjacent AI infrastructure paper.
- One plausible but irrelevant paper.

Work:

- Run the complete workflow with concurrency enabled.
- Inspect every artifact rather than only the final brief.
- Plant or manually create one unsupported claim to prove the critic catches it.
- Exercise one failed validation or retry path.
- Fix only failures that prevent the promised workflow or make its output misleading.

Gate: all three papers reach a visible terminal state and the brief accurately represents the failure/retry experiment.

### 6:15-7:10 — produce the demonstration run

Work:

- Fetch 10-15 papers for one narrow, defensible query such as `HBM memory inference bandwidth` or `CXL disaggregated memory datacenter`.
- Freeze the selected input set before model calls.
- Run readers in bounded parallel, followed by critics in bounded parallel.
- Do not adjust the rubric to make preferred papers rank higher.
- If model time is too long, complete at least five papers and report the remainder as not completed; do not fabricate a top 10.
- If at least 20 minutes remain in this block, compare reader-only and reader-plus-critic outcomes on 3 papers and record cost, latency, and unsupported-claim counts.

Gate: `out/brief.md` is a genuine product of the documented quickstart and includes visible incomplete, failed, and unresolved counts.

### 7:10-8:00 — harden the presentation and rehearse

Work:

- Run the deterministic test suite and the README quickstart from a clean shell.
- Update the README status table honestly.
- Remove or clearly label dead scaffolding such as `main.py` and `scripts/lang_chain_test.py`; do not spend time polishing unused experiments.
- Add measured run facts to `docs/evaluation.md`: paper count, schema-valid rate before retry, unsupported/overclaimed count, unresolved/failed count, wall time, and token/cost data if available.
- Check `git diff`, confirm generated secrets or private material are absent, and make a final coherent commit.
- Spend the final 20 minutes explaining the system aloud without reading.

Gate: a new person can clone the project, follow the quickstart, understand its limitations, and inspect why a paper received its position.

## Ranking rule: prefer the simplest defensible version

For the eight-hour MVP, keep the current `relevance` and `importance` 0-5 scores plus `extendable` rather than forcing a database redesign.

One acceptable published rule is:

```text
base_score = 12 * relevance + 8 * importance
```

This produces 0-100 and intentionally weights relevance to the public Micron-oriented lens more than general scientific importance. `extendable` is a displayed attribute and a tie-breaker, not an arbitrary score bonus. Critic failures are gates, not hidden numeric penalties.

Tie-break in this order:

1. Eligible (`prioritize`/`watch`) before `needs_review`.
2. Base score descending.
3. Relevance descending.
4. Extendable before not extendable.
5. Published/submitted date descending.
6. arXiv ID ascending.

If the full pipeline is complete early, the five-dimension rubric proposed in `assessment_on_agentic_infa.md` is a reasonable next experiment. Do not switch scoring instruments during the demonstration run, because that makes results incomparable.

## Tests that matter most

Prefer a dozen high-value deterministic tests over broad test coverage.

- arXiv ID version normalization and deduplication.
- Stable fetch sorting and limit behavior.
- Stable canonical JSON hashing.
- Reader schema success and representative failures.
- A null or nonexistent source span cannot be supported.
- Critic covers every claim exactly once.
- Critic cannot reference a claim from a different reader run.
- Invalid ingestion rolls back completely.
- Duplicate artifact ingestion is idempotent.
- Retry count never exceeds one.
- Rank gates and tie-breaks behave exactly as documented.
- A missing terminal paper blocks a successful report.
- Report generation works from stored artifacts without calling a model.

## What to cut if the schedule slips

Cut in this order:

1. Five-dimension scoring.
2. Run manifests beyond existing hashes and trace fields.
3. The reader-versus-reader-plus-critic ablation.
4. A committed example run.
5. SQLite schema enhancements that are not required for the brief.
6. Demonstration-set size from 15 toward 5.

Do not cut the schema, exact source spans, critic, bounded retry, deterministic ranker, trace, visible failures, or end-to-end run. Those are the project's thesis.

If network access fails, use the cached arXiv fixture to demonstrate the entire pipeline and state that the live-fetch step was fixture-backed. If a model call fails, preserve the failure and continue other independent papers. If the critic is not operational by the end of hour four, stop adding features and make the reader-critic path work on one paper.

## Twenty-minute explanation rehearsal

Be able to answer these without notes:

### What problem does this solve?

It reduces a bounded arXiv result set to a ranked, evidence-backed brief for a public datacenter-memory lens. It is a triage aid, not an oracle for global novelty or company strategy.

### Why agents at all?

Reading technical language, mapping it to a strategic lens, and challenging semantic claims require judgment. Fetching, validation, hashing, persistence, ranking, and rendering do not, so scripts handle them.

### Why exactly three roles?

The orchestrator controls the fixed workflow. A reader extracts claims and proposes clearly labeled inferences. An isolated critic tests those claims against the same source. More roles would add cost and correlated opinions without an evaluated benefit.

### Where is parallelism?

Papers are independent, so reader calls fan out concurrently. After validation, critic calls fan out concurrently. Within one paper, reader then critic remains sequential because the critic depends on the reader artifact.

### How is it reproducible?

The system preserves the exact input abstracts, arXiv versions, hashes, agent definitions, model IDs, structured outputs, validation results, attempts, and deterministic rank policy. That reconstructs what happened even though an LLM replay may not be byte-identical.

### How is data stored?

Files hold the evidence artifacts, JSONL records execution events, and SQLite provides a queryable index over validated facts and judgments. Paths locate artifacts; SHA-256 hashes prove which bytes were used.

### Why use a critic?

The reader is optimized to extract and synthesize; it may overreach. The critic independently checks every claim and relevance link. Its value should eventually be justified by a frozen-input ablation, not assumed.

### Why no LangGraph, RAG, cloud, or dashboard?

The workflow is fixed and the assignment is unknown. Direct, visible control flow makes the proof easier to test and explain. Each deferred technology has a clear insertion point after a measured need appears.

### What are the most important limitations?

- Abstract-only evidence is insufficient for deep method, limitation, baseline, and novelty assessment.
- Exact quotation proves location, not truth or full-paper entailment.
- The reader and critic can share correlated model errors.
- Ranking arithmetic is deterministic, but its input judgments are not objective facts.
- Micron relevance and future impact are labeled analyst inferences based on a public lens.
- arXiv provenance normally means preprint, not peer-reviewed validation.

## Final definition of done

The sprint is complete only when all of the following are true:

- A real query has passed through fetch, reader, validation, critic, bounded retry handling, ranking, and report generation.
- At least five papers have terminal states; the target remains 10-15.
- Every brief claim carries an arXiv ID, source span status, evidence type, provenance, and critic verdict.
- Unresolved and failed counts appear at the top of the brief.
- No fetched paper disappears between input and output.
- Trace data identifies every model attempt and the exact artifacts it used and produced.
- Deterministic tests pass.
- The README quickstart works as written and its status table is honest.
- You can explain the complete flow, storage model, concurrency, reliability boundaries, scoring rule, and deferred extensions in five minutes.

The success criterion is not how much infrastructure exists. It is whether a skeptical engineer can inspect one ranked claim, follow it back through the entire workflow, and understand both why the system made the judgment and where that judgment could be wrong.
