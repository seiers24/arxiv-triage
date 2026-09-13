# Core 2.0 implementation review gates

**Status:** exact Core 2.0 contracts approved; agent behavior under review

**Created:** 2026-09-12

This document tracks decisions and files that must be reviewed before the
core `2.0` implementation is committed, pushed, or used as an authoritative
agent workflow. It is a review checklist, not an agent instruction file.

## Safe implementation scope in progress

The following deterministic foundations may be implemented without deciding
research behavior:

- strict models for fields and relationships explicitly defined by the core
  specification;
- atomic artifact writes and collision checks;
- append-only trace events and idempotent replay;
- a caller-selected SQLite `2.0` database and deterministic rebuild support;
- explicit workflow states, legal transitions, dispatch barriers, retry
  counters, and concurrency-bound validation;
- network-free fixtures and tests.

The legacy `1.0` scripts and database remain unchanged during this additive
implementation.

## Approved exact contract definitions

The formerly blocking definitions are now exact in `docs/schema.md`, the Core
platform specification, and `src/arxiv_triage/models/`:

1. the complete `ReviewerTask`
2. `ReviewRecord.challenges[]`
3. `ReviewRecord.human_review_items[]`
4. the complete `AgentRun` artifact
5. self-hash construction for every hash-addressed object
6. identifier, repository-relative path, and timestamp constraints
7. the complete `validation.json` contract
8. the complete `outcome.json` contract

The approved forms minimize duplicate state: assessment labels are absent for
the sole integer score type, critic review gating derives from reasons,
accounting validity derives from enforced equations, and reviewer human-review
items reference challenges. Reader and critic tasks embed and hash-bind the
exact normalized source text required by tool-free workers.

## SQLite migration decision

The proposed `2.0` schema reuses table names from the incompatible `1.0`
database. The implementation will not drop, rewrite, or auto-migrate existing
tables.

Approved rollout: use `data/triage-v2.db`; any in-place `1.0` migration is a
separate future decision. Canonical JSON and the trace remain authoritative,
and the fresh index is reversible.

## Approved minimal ReaderRecord decision

The Core `2.0` reader record has one evidence-bearing collection, `claims`, and
retains only its identity metadata, `problem`, `method`, `claims`, and
`warnings`. `contributions`, `experimental_evidence`, `limitations`,
`assumptions`, and `focused_observations` are removed from the universal
contract. `claims` may be empty; the reader must not invent filler when no
useful source-bound claim can be extracted, and at least one warning must then
explain the empty collection.

Reader output passes through one deterministic validation gateway before
canonical promotion. The gateway owns parsing, structure, identity, hash,
cross-artifact, and exact-locator checks; semantic support remains the critic's
judgment.

## Approved invalid-run lifecycle decision

`invalid` is terminal for the physical attempt. It is not followed by a separate
`agent_run.failed` event for the same invocation. A permitted retry receives a
new run ID and incremented attempt number. Exhausted invalid attempts can fail
the logical job without changing their precise physical-run outcomes.

## Approved blocked-review lifecycle decision

The investigation state machine includes `review_blocked`. A valid review with
`report_status: blocked` enters that state rather than the infrastructure-
oriented `failed` state and cannot proceed to rendering without a later defined
resolution workflow.

## Approved corpus accounting decision

The corpus is the complete frozen, deduplicated set of discovered candidates.
Raw provider results and duplicates remain visible in the discovery ledger but
do not inflate the corpus. Membership states are `included`, `excluded`, and
`membership_unresolved`. The latter means discovery or identity work could not
route the candidate; a conservative screener `needs_review` result is included
and analyzed.

Only included papers receive reader and critic jobs. Their terminal analysis
states are `complete`, `analysis_unresolved`, and `failed`. Reviewer and rendered
accounting retain all seven counts and enforce:

```text
expected = CorpusManifest.counts.discovered
expected = included + excluded + membership_unresolved
included = complete + analysis_unresolved + failed
```

`expected` is therefore the total frozen corpus size, while analysis outcome
counts cover included papers only.

## Remaining agent-behavior files requiring explicit approval

Any changes to the following are behavior changes and remain pending review:

- `AGENTS.md`
- `docs/roles/orchestrator.md`
- `.claude/agents/paper-screener.md`
- `.claude/agents/paper-reader.md`
- `.claude/agents/critic.md`
- `.claude/agents/reviewer.md`
- `.claude/agents/orchestrator.md`, if introduced
- `.claude/skills/**/SKILL.md`
- dispatcher correction prompts, model routing, retry prompts, and component
  rubrics wherever implemented

These files must not be committed or pushed as part of the core rollout until
their diffs have been presented for human review and explicitly approved.

## Tools intentionally out of scope

This core pass does not add Tavily, workshop discovery, proposal conversion,
proposal relevance search, a vector database, a UI, a workflow framework, or
unbounded autonomous search. Those belong to component-specific plans after
the core contracts are accepted.
