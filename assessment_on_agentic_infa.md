# Assessment of Agentic Infrastructure for `arxiv-triage`

**Assessment date:** 2026-09-07  
**Reference systems:** `/home/zenithblade/workspace/lexicon` and `/home/zenithblade/workspace/arxiv-triage`  
**Scope:** Architecture and evidence review only. No agents were launched and no project files were changed.

## Executive assessment

`arxiv-triage` should be a fixed, inspectable workflow with probabilistic workers—not an autonomous swarm. Its current design is already directionally correct: deterministic scripts fetch, validate, store, rank, and render; bounded agents interpret papers and challenge conclusions.

The best Lexicon ideas to transfer are:

1. Immutable, hash-bound input packets.
2. Typed separation between source facts and analyst inference.
3. Role-specific context and independent criticism.
4. Call receipts that bind inputs, prompts, schemas, models, and outputs.
5. Fail-closed validation, bounded retries, and visible unresolved states.
6. Deterministic score calculation and tie-breaking.
7. Files as the inspectable evidence record, with SQLite as an index.

Do not copy Lexicon's full scale. Four-candidate generation, large reader panels, long relay state, manuscript transactions, and extensive process-recovery machinery solve problems that this proof of concept does not have.

The recommended minimum remains one orchestrator and two workers:

- `paper-reader`: extracts technical claims and develops explicitly labeled strategic hypotheses.
- `critic`: independently tests source support, novelty language, Micron relevance, and extension feasibility.
- Orchestrator: follows a fixed runbook, dispatches bounded calls, and never substitutes its own unsupported conclusions.

This follows Anthropic's distinction between predictable workflows and open-ended agents: use predefined code paths when the steps are known, and add complexity only when evaluation shows a benefit. See [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents).

## Current `arxiv-triage` state

The repository contains a strong design skeleton but not yet an end-to-end system.

| Existing element | Assessment |
|---|---|
| `AGENTS.md` | Correctly separates deterministic scripts from judgment-bearing agents and defines bounded retries. |
| `scripts/db.py` | Good foundation: append-oriented runs, transactional ingestion, artifact path plus SHA-256, and agent-definition/model versioning. |
| `data/triage.db` | Schema exists and is empty; no demonstrated research run is stored. |
| `paper-reader` | Only a partial prompt exists. |
| `critic`, `fetch.py`, `rank.py`, runbook | Not implemented. |
| `docs/schema.md`, `docs/decisions.md`, `docs/evaluation.md` | Empty, so important contracts currently live in duplicated prose or code. |
| Source depth | Abstract-only by design. This is acceptable for the first smoke test but insufficient for strong novelty, evidence, limitation, or extension judgments. |
| Dashboard | Not built, appropriately deferred until the CLI workflow works. |

There is already documentation drift that should be resolved before implementation:

- `AGENTS.md` and `README.md` describe `logs/trace.jsonl`; `HANDOFF.md` says the SQLite `runs` table is the only trace.
- `AGENTS.md` assigns validation to `scripts/validate.py`; `HANDOFF.md` assigns validation and storage to `scripts/db.py`.
- The repository now has a baseline Git commit, while the handoff still says it has no commits.

Choose one canonical contract in `docs/`, link to it from agent instructions, and remove duplicate operational rules. Lexicon's history shows that copied rules drift even when every copy was initially correct.

## Lexicon concepts worth reusing

### 1. Separate control, data, and authority

Lexicon distinguishes three different graphs:

- **Control:** which stage runs next.
- **Data:** which exact artifacts a stage receives.
- **Authority:** which component may interpret, recommend, approve, or mutate state.

Apply the same separation here:

- Python controls the workflow.
- Versioned packets carry data between stages.
- Agents may propose judgments.
- The ranker applies the published formula.
- The human decides whether a finding is strategically useful.

A critic verdict must not silently rewrite a reader record. A high score must not become a statement of Micron strategy. The dashboard must not imply that publication equals human approval.

### 2. Build a paper packet before any model call

Lexicon treats context assembly like a compiler: resolve sources, validate them, emit a bounded packet, record dependencies, and refuse stale reuse.

For each arXiv paper, create one immutable packet containing:

- Exact arXiv ID and version.
- Canonical metadata JSON.
- Abstract and, after the smoke test, normalized full text with page boundaries.
- PDF/text SHA-256 values.
- Fetcher and extractor versions.
- The current Micron-oriented strategic lens and its hash.
- Prompt and output-schema hashes for the next role.

The model should never fetch or browse. It receives this packet and returns one schema-bound artifact.

### 3. Distinguish paper claims from strategic inference

Lexicon does not allow research evidence, story facts, artistic judgment, and author approval to collapse into one `verified` flag. `arxiv-triage` needs the equivalent distinction:

| Record class | What it means | Required support |
|---|---|---|
| `paper_claim` | The paper explicitly states or demonstrates this. | Exact source span, page/section, paper hash. |
| `author_claimed_novelty` | The authors describe the contribution as novel. | Exact source span; not treated as global novelty proof. |
| `analyst_inference` | The workflow inferred an implication. | Linked paper-claim IDs plus stated reasoning and assumptions. |
| `strategic_hypothesis` | A possible Micron-oriented opportunity or risk. | Linked claims, mechanism chain, horizon, dependencies, and falsification test. |
| `extension_proposal` | A way to build on the work. | Hypothesis, experiment, metric, baseline, and required resources. |

This boundary is essential. A paper can support “bandwidth demand increased” without itself supporting “Micron should build product X.” The second statement is a labeled strategic inference.

### 4. Use content-addressed call receipts

Lexicon reuses an output only when a completed receipt matches the exact input identity and output hash. Adopt the same rule.

```text
call_id = SHA256(canonical_json({
  paper_packet_sha256,
  role,
  prompt_sha256,
  schema_sha256,
  requested_model,
  model_parameters
}))
```

A valid receipt should record:

- `status`: `running | complete | invalid | failed`.
- Requested and resolved model IDs when available.
- Input and output SHA-256 values.
- Prompt and schema versions.
- Start/end time, duration, token usage, and cost when available.
- Validation result and retry number.
- Artifact path.

Do not include timestamps in `call_id`; the same logical input should have the same identity. A rerun after a valid cache miss remains a distinct attempt linked to the same call identity.

### 5. Fail closed and preserve failed attempts

Lexicon does not let missing branches become a polished aggregate. Use the same rule:

- Every fetched paper must end as `complete`, `unresolved`, or `failed`.
- A malformed output receives one retry with the validation error.
- A critic rejection permits one reader re-read.
- After that, preserve both attempts and mark the paper `unresolved`.
- Never remove failed papers before ranking; count and display them.
- Never publish a successful run status if any expected paper lacks a terminal state.

The loop is bounded because the system is triage, not debate. Repeated agent discussion tends to increase cost and agreement without proving correctness.

### 6. Isolate the critic by information contract

The critic should receive:

- The frozen source packet.
- The reader's structured claims and strategic findings.
- The critic rubric and schema.

It should not receive:

- The reader's hidden reasoning or conversation transcript.
- The paper's preliminary overall rank.
- Other agents' opinions.
- A target conclusion such as “prove this matters to Micron.”

The critic returns a verdict for every claim and strategic finding: `supported`, `qualified`, `rejected`, or `unresolved`. It does not rewrite the record. Python joins the two artifacts.

### 7. Keep aggregation deterministic and modest

Lexicon demonstrates an important limit: deterministic arithmetic does not make model judgments deterministic. `arxiv-triage` should state the same limitation prominently.

Use five rubric dimensions, each scored 0–5:

| Dimension | Weight | Question |
|---|---:|---|
| Micron-oriented relevance (`R`) | 30% | Does the work materially touch memory, storage, interconnect, packaging, reliability, or AI memory-system demand? |
| Technical novelty (`N`) | 20% | Is the contribution more than a parameter change or repackaging, within the evidence available? |
| Evidence strength (`E`) | 15% | Are claims supported by real hardware, simulation, formal analysis, or clearly reported experiments? |
| Three-to-five-year fit (`H`) | 15% | Could the mechanism affect competitive decisions in the target horizon? |
| Extension value (`X`) | 20% | Is there a concrete, testable path to build on the work? |

```text
priority_score = round(20 * (0.30R + 0.20N + 0.15E + 0.15H + 0.20X))
```

Deterministic gates:

- Any rejected load-bearing source claim makes the paper `needs_review` rather than `prioritize`.
- Novelty supported only by the authors' own novelty language is capped at `N = 2`.
- `evidence_type = none_stated` is capped at `E = 1`; formal theory is scored by its own rubric, not automatically penalized.
- An unresolved Micron relevance chain makes the paper `needs_review` regardless of its numeric score.
- Suggested buckets: `prioritize` at 75–100, `watch` at 55–74, and `archive` below 55.

Deterministic tie-breaking:

1. Final score descending.
2. Micron relevance descending.
3. Extension value descending.
4. Latest submitted version descending.
5. arXiv ID ascending.

The formula and gates are reproducible given validated inputs. The underlying 0–5 judgments remain model assessments and should be evaluated against human labels.

### 8. Use files as evidence and SQLite as the index

Lexicon's inspectable files are easier to audit than opaque framework state. Keep that property while using the existing SQLite store for lookup.

```text
runs/<run_id>/
  manifest.json
  status.json
  inputs/query.json
  inputs/arxiv-response.json
  papers/<arxiv-id-version>/packet.json
  papers/<arxiv-id-version>/source.txt
  papers/<arxiv-id-version>/reader.json
  papers/<arxiv-id-version>/critic.json
  papers/<arxiv-id-version>/decision.json
  attempts/<call-id>/<attempt>.json
  report.md
```

Compute the run fingerprint from canonical JSON containing the query, exact arXiv response hash, paper packet hashes, pipeline version, route configuration, prompt/schema hashes, strategic-lens hash, and scoring-policy hash. Store the full fingerprint internally and a short prefix for display.

Extend the current database with:

- `workflow_runs`: run fingerprint, status, manifest path/hash, query, start/end times.
- `run_papers`: one expected terminal state per paper.
- `calls`: call identity, attempt number, input/output hashes, route, usage, status, artifact path.
- `decisions`: component scores, gates, final score, bucket, critic status, decision artifact path/hash.
- Source coordinates and source hash columns on `claims`.

The JSON artifacts remain the source of truth. SQLite locates and summarizes them. Database rows should be written only after artifact validation and inside one transaction, as `scripts/db.py` already does.

### 9. Store decisions, not hidden chain of thought

Transparency does not require saving private model reasoning. Save concise, inspectable decision records:

- What input was used.
- Which rubric rule was applied.
- Which evidence spans support the result.
- Which assumptions connect a paper claim to a strategic inference.
- Which critic challenge changed or blocked the result.
- Why the deterministic ranker assigned its bucket.

This is more useful than a conversational transcript and safer to display in a portfolio.

## Recommended workflow

```text
Query
  -> deterministic arXiv fetch, sort, version-dedupe
  -> deterministic paper packet build and hashing
  -> parallel paper-reader calls, one per paper
  -> schema and exact-span validation
  -> parallel critic calls, one per valid reader record
  -> at most one source-bound re-read when critique fails
  -> deterministic gates, scoring, and tie-breaking
  -> SQLite indexing and Markdown report
  -> read-only dashboard
  -> human review
```

Parallelize across papers, because they are independent. Keep each paper's reader → critic → decision chain sequential. Agents should exchange only validated artifacts through the orchestrator; they should not message one another directly.

### Strategic lens

Put the Micron-oriented lens in one versioned configuration file rather than repeating it across prompts. Use public, editable categories rather than implying access to confidential company strategy:

- DRAM, NAND, HBM, SSD, and memory hierarchy.
- CXL, disaggregated memory, chiplets, packaging, and interconnect.
- Processing-in-memory and near-memory computing.
- Bandwidth, capacity, latency, energy, thermal, endurance, and reliability constraints.
- AI training/inference workload changes that alter memory demand.
- Manufacturing/process implications and ecosystem or standards dependencies.

Every strategic finding should identify its category, value-chain layer, implication type, horizon, dependencies, and testable extension.

### Novelty boundary

The proof of concept cannot establish global novelty from one paper or one arXiv query. Report three separate concepts:

- `author_claimed_novelty`.
- `analyst_assessed_novelty`.
- `corpus_relative_novelty` against the exact fetched set.

Do not render any of these as “proven novel.” A broader literature search would be a separately scoped extension.

## Minimal dashboard

Build the dashboard only after one complete CLI run. It should be read-only and never trigger model calls.

The initial dashboard needs three views:

1. **Run summary:** query, manifest hash, models, prompts/schemas, paper counts, failures, unresolved items, duration, and cost.
2. **Ranked papers:** bucket, score, strategic theme, evidence type, critique status, and one-sentence implication.
3. **Paper detail:** source metadata, extracted claims and spans, Micron relevance chain, extension proposal, critic dispositions, score breakdown, and links to raw artifacts.

Badges should distinguish `paper-stated`, `analyst-inferred`, `critic-qualified`, `unresolved`, and `human-reviewed`. A small Streamlit application reading SQLite is sufficient; a frontend framework is unnecessary for the portfolio proof.

## Evaluation plan

Evaluation is what justifies the multi-agent cost.

### Golden set

Hand-label 20–30 papers across clearly relevant, adjacent, and irrelevant categories. Record:

- Key contributions expected from the paper.
- Whether each sampled claim is supported by its cited span.
- Micron-oriented relevance and importance scores.
- Whether a proposed extension is concrete and technically plausible.
- Final priority bucket.

### Component metrics

- Schema-valid response rate before retry.
- Exact source-span validity rate.
- Claim support precision on a human-audited sample.
- Critic precision and recall for planted or hand-labeled unsupported claims.
- Rate of unresolved and failed papers.
- Token cost and latency per paper.

### End-to-end metrics

- Top-five recall of human-prioritized papers.
- Rank correlation with human ordering.
- Fraction of displayed strategic findings judged useful and defensible.
- Stability of the full score vector across repeated runs, not only stability of the mean.

### Required ablation

Compare the same frozen papers under:

1. Reader only.
2. Reader plus critic.

Keep paper bytes, prompts, schemas, model IDs, and scoring policy fixed. The critic earns its place only if it reduces unsupported or overclaimed findings enough to justify added cost and latency. Add a separate strategic-mapper agent only if a later ablation shows that combining extraction and strategic mapping in `paper-reader` produces a measurable failure mode.

### Deterministic tests

No-model tests should cover:

- arXiv version deduplication and stable sorting.
- Canonical JSON and run/call hashing.
- Stale packet and altered output rejection.
- Exact source-span validation.
- Schema and enum failures.
- Retry-limit enforcement.
- Missing-paper prevention at aggregation.
- Score caps, thresholds, and tie-breaks.
- SQLite rollback on partial ingestion.
- Dashboard/report reconstruction without model calls.

## What not to transfer from Lexicon

- Four-arm candidate generation and order-swapped judges.
- Eight-reader panels or model voting presented as independent consensus.
- Stateful whole-document reader relays for the first version.
- Autonomous agent-created subtasks.
- A vector database or knowledge graph before cross-run retrieval is measured as necessary.
- Manuscript-grade seating transactions; arXiv-triage publishes reports, not irreversible source edits.
- Complex process-group cleanup until direct subprocess execution demonstrates an orphan/timeout problem.
- Large duplicate backup trees. Content-addressed artifacts, append-only attempts, and Git history are enough.

## Implementation priorities

### P0 — complete the existing MVP

1. Resolve the trace and validation documentation contradictions.
2. Populate the canonical schema, decisions, and evaluation documents.
3. Implement deterministic fetch, validation, ranking, and report generation.
4. Finish `paper-reader`, add `critic`, and write the fixed runbook.
5. Demonstrate one query over 10–15 abstracts end to end.

### P1 — import the high-value Lexicon controls

1. Add immutable paper packets and full input/output call receipts.
2. Separate paper claims, strategic inferences, and extension proposals in the schema.
3. Add exact span/page validation and full-paper extraction.
4. Add run manifests, content-derived identities, stale-input checks, and complete-paper aggregation gates.
5. Run the reader-only versus reader-plus-critic ablation.

### P2 — portfolio presentation

1. Add the read-only dashboard.
2. Include one sanitized example run and its manifest.
3. Publish the golden-set results, cost, latency, failures, and limitations.
4. Add a short “How I worked” section distinguishing human decisions, deterministic code, and model contributions.

Stop after P0 if time is constrained. A complete, evaluated abstract workflow is a stronger portfolio artifact than an unfinished full-paper platform.

## Key limitations to disclose

- arXiv papers are commonly preprints; provenance is not peer-review validation.
- Exact quotation proves source location, not that the claim is entailed.
- Model roles can share correlated errors even when prompts and calls are isolated.
- Numeric scoring is deterministic aggregation over nondeterministic judgments.
- Abstract-only analysis cannot reliably assess methods, limitations, baselines, or claimed evidence.
- Micron relevance is an analyst inference unless the source explicitly discusses the company.
- Three-to-five-year impact is a forecast with assumptions, not a paper fact.
- Prompt, schema, strategic-lens, and model changes create a new instrument version; scores should not be compared silently across versions.

## Lexicon evidence reviewed

The recommendations above were derived primarily from:

- `AGENTS.md`
- `ops/README.md`
- `ops/codex/README.md`
- `ops/codex/pipeline.py`
- `ops/codex/common.py`
- `ops/codex/routes.json`
- `ops/codex/corpus.py` and `research-README.md`
- `ops/codex/panels.py` and `panel-README.md`
- `ops/codex/editorial_memory.py` and `memory-README.md`
- `ops/codex/continuity.py`
- `ops/codex/runtime-guard-README.md`
- `ops/audits/panel-validity-review-2026-09-07/`
- `ops/audits/explanatory-workflow-guide-2026-09-07/technical-companion/`

The most transferable lesson is not “use more agents.” It is: make every probabilistic judgment pass through an explicit data contract, preserve its evidence, and let deterministic code control what may happen next.
