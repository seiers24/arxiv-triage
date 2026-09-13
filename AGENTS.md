# Agent master file

Repository-wide instructions for every agent working in `arxiv-triage`.
Directory-scoped `AGENTS.md` files override this file where the index below
lists them.

Read [`docs/README.md`](docs/README.md) first. This file contains shared
constraints; repository documentation contains the canonical contracts,
decisions, role descriptions, evaluation procedure, and implementation plans.
Where they overlap, the documentation is the source of truth.

## Project purpose

`arxiv-triage` turns an arXiv query and a versioned research objective into a
ranked, evidence-backed brief. The objective determines relevance and ranking;
it never changes whether a paper supports a claim.

Every displayed claim must resolve to its exact fetched source and arXiv ID.
Every model attempt must leave a trace. Screening decisions, degraded source
fallbacks, unresolved objections, and failures remain visible.

## Canonical references

- [`docs/schema.md`](docs/schema.md): JSON contracts and validation rules.
- [`docs/decisions.md`](docs/decisions.md): accepted design decisions and
  alternatives.
- [`docs/evaluation.md`](docs/evaluation.md): offline human evaluation; never a
  runtime worker prompt.
- [`docs/roles/orchestrator.md`](docs/roles/orchestrator.md): authority and
  boundaries of the main orchestrator.
- [`docs/planning/full-text-pipeline-plan.md`](docs/planning/full-text-pipeline-plan.md): planned
  screening and full-text implementation.
- [`objectives/README.md`](objectives/README.md): objective-profile authoring.

Do not duplicate these contracts in this file.

## Shared instructions

### Think before assuming

- Surface ambiguity, competing interpretations, and important tradeoffs.
- Keep a finding `unverified` until the active workflow's critic checks it
  against the same frozen source.
- Record peer-review status as provenance, not proof of correctness.
- State when available evidence cannot resolve a paper-level question.
- Prefer a simpler approach when it preserves the documented guarantees.

### Scripts do deterministic work; agents do judgment

- Scripts own network acquisition, normalization, deduplication, hashing,
  document extraction, validation, persistence, deterministic screening rules,
  ranking, and report rendering.
- Agents own bounded semantic judgments: abstract screening, paper reading,
  claim extraction, objective assessment, and criticism.
- Workers never fetch sources, perform basic extraction, invoke scripts, or run
  other agents.
- The orchestrator invokes scripts and dispatches workers; it does not perform
  worker judgments or rewrite worker artifacts.
- If a step can be performed deterministically, implement it in a script.

### Evidence and objective separation

- Evidence type, provenance, source support, and critic verdict meanings are
  universal and follow `docs/schema.md`.
- Research scope, relevance categories, extension priorities, and ranking
  weights come from the selected objective profile.
- Bind every objective-dependent artifact to `objective_id` and
  `objective_hash`.
- Never compare or combine numeric scores from different objective hashes as
  though they share a scale.
- Never cite an inferred statement as something the paper says.
- A claim without a valid source span cannot be `supported`.

### Bounded work and visible outcomes

- Every loop, retry, batch, and concurrency setting has an explicit bound.
- Never retry an agent beyond the active schema and runbook allowance.
- Continue independent work when one candidate or paper fails.
- Never silently drop a fetched candidate, screening decision, invalid model
  artifact, extraction failure, abstract-only fallback, or unresolved paper.
- Do not fill a requested result count by hiding failures or substituting
  unreported candidates.
- Preserve raw invalid attempts before correction or retry.

### Artifacts and persistence

- Validated JSON artifacts are the complete evidence source of truth.
- JSONL is the append-only execution ledger, including failed attempts.
- SQLite is a rebuildable query index over validated artifacts; it must not
  define a competing contract or become the only copy of a run.
- A path locates an artifact; a cryptographic hash identifies its exact bytes.
- Deterministic persistence must be transactional and idempotent where the
  documented contract requires it.

## Runtime roles

Role-specific behavior belongs in the linked role or worker definition, not in
this repository-wide file.

| Role | Kind | Definition |
|---|---|---|
| Orchestrator | Main interactive session | `docs/roles/orchestrator.md`; executable runbook in `.claude/skills/triage-topic/SKILL.md` |
| Paper screener | Batched worker, pending exact screening schema | `.claude/agents/paper-screener.md` |
| Paper reader | Per-paper worker | `.claude/agents/paper-reader.md` |
| Critic | Per-record adversarial worker | `.claude/agents/critic.md` |
| Reviewer | Per-investigation corpus worker | `.claude/agents/reviewer.md` |

If a required definition or runbook is missing, report that the workflow is not
implemented; do not improvise an undocumented role.

The hierarchy remains one level deep: the main orchestrator may dispatch
workers, and workers may not dispatch other agents.

## Change protocol

The schema is the contract between agents and scripts. For a contract change:

1. Record or amend the design decision when architecture or tradeoffs change.
2. Update `docs/schema.md` and increment incompatible schema versions.
3. Update Pydantic validation in `scripts/validate.py`.
4. Update affected worker definitions and the orchestration runbook.
5. Update persistence, deterministic scripts, fixtures, and tests.
6. Update evaluation labels or metrics only when their meaning changes; never
   tune them merely to make a result pass.

## Project prohibitions

- Do not build a UI, vector store, knowledge graph, container platform, or
  other deferred system unless a user explicitly moves it into scope and the
  decision is recorded.
- Do not add or repurpose a worker role without a decision entry and updated
  role index.
- Do not present a ranked brief without all counts required by the active
  schema and runbook.
- Do not cite or analyze a source that was not fetched and frozen for the run.
- Do not treat an abstract-only packet as full-text evidence.
- Do not expose golden evaluation labels to runtime workers.

## Working with this repository

- Use Python 3.12 or newer and `uv` for Python commands.
- Keep secrets in `.env`; never commit them or copy them into artifacts.
- Model calls made from Python must record token counts and cost when available
  in the same execution ledger.
- Record design decisions in `docs/decisions.md`, including alternatives and
  tradeoffs.
- Preserve unrelated user changes in a dirty worktree.

## Directory-scoped instructions

None currently.

| Path | Scope |
|---|---|
| — | — |
