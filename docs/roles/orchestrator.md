# Orchestrator role

## Purpose

The orchestrator is the main interactive session responsible for turning a
query and objective profile into a complete, auditable brief. It controls the
workflow; deterministic scripts transform data and role-specific workers make
bounded judgments.

This is a human-readable role definition, not a dispatchable worker prompt.
The executable procedure belongs in
`.claude/skills/triage-topic/SKILL.md`.

## Inputs and result

The orchestrator receives:

- An arXiv query.
- A selected objective profile.
- Optional bounded run settings such as candidate limit and concurrency.

It produces a ranked brief plus the frozen sources, model artifacts,
validation results, trace events, terminal states, and rebuildable SQLite
index needed to audit the run.

## Responsibilities

- Validate and freeze the selected objective profile.
- Invoke deterministic scripts for query, normalization, deduplication,
  source acquisition, extraction, validation, persistence, and ranking.
- Dispatch batched abstract screening and preserve every screening decision.
- Route `selected` and `needs_review` candidates to full-text preparation;
  never silently discard `screened_out` candidates.
- Dispatch paper readers and critics with bounded concurrency.
- Keep each paper's dependent stages in order while allowing independent
  papers to progress concurrently.
- Enforce the single permitted retry or re-read and then stop visibly.
- Ensure every candidate and selected paper reaches a defined terminal state.
- Record hashes, paths, models, validation outcomes, errors, retries, tokens,
  and cost when available.
- Refuse to report success when required artifacts or terminal states are
  missing.

## Authority

The orchestrator may:

- Invoke repository scripts with explicit inputs and output paths.
- Dispatch only the worker roles defined by the active workflow.
- Retry only where the schema and runbook authorize it.
- Continue independent papers when another paper fails.
- Mark an item `needs_review`, `unresolved`, or `failed` when its documented
  gate requires that state.

## Boundaries

The orchestrator must not:

- Fetch or extract sources through model judgment when a deterministic script
  owns that operation.
- Personally read papers, screen abstracts, extract claims, or issue critic
  verdicts.
- Rewrite a worker artifact to make it validate or change its conclusion.
- Hide a screening decision, failed extraction, invalid artifact, unresolved
  objection, or abstract-only fallback.
- Change an objective, scoring policy, prompt, model route, or evaluation label
  after seeing results without starting a separately identified run.
- Create recursive delegation, unbounded retries, or uncontrolled fan-out.
- Compare scores produced under different objective hashes as if they shared a
  scale.

## Scale and concurrency

A run may contain many logical reader and critic tasks, but the orchestrator
uses bounded worker pools rather than launching every task simultaneously.
Candidate screening should be batched. Full-text acquisition begins only after
screening, and critic work begins only after the corresponding reader record
passes validation.

Concurrency limits are explicit run settings and must respect provider limits,
local resources, and cost constraints. Changing concurrency may affect wall
time, but it must not change deterministic selection, validation, or ranking.

## Failure behavior

Failures are data. The orchestrator preserves the failed attempt and its error,
assigns the documented state, and continues work that does not depend on it.
It never fills a requested result count by erasing failures or silently
substituting lower-ranked papers.
