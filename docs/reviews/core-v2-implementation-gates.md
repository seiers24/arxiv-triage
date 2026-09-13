# Core 2.0 implementation review gates

**Status:** pending human review  
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

## Blocking contract definitions

The architecture specification intentionally describes some payloads at a
summary level. Code and agent prompts need exact contracts for:

1. `ReaderRecord.contributions[]`
2. `ReaderRecord.experimental_evidence[]`
3. `ReaderRecord.limitations[]`
4. `ReaderRecord.assumptions[]`
5. `ReaderRecord.focused_observations[]`
6. the complete `ReviewerTask`
7. `ReviewRecord.challenges[]`
8. `ReviewRecord.human_review_items[]`
9. the complete `AgentRun` artifact
10. self-hash construction for every hash-addressed object
11. identifier, repository-relative path, and timestamp constraints
12. whether `agent_run.invalid` is terminal for a physical attempt or must
    always be followed by a separate `agent_run.failed` event
13. the investigation state entered when a valid reviewer returns
    `report_status: blocked`
14. the complete `validation.json` contract
15. the complete `outcome.json` contract
16. whether corpus `membership_status` includes `unresolved`, as the SQLite
    schema permits but the manifest summary does not define
17. whether reviewer terminal accounting covers all discovered entries or
    included papers only

Until these are approved, implementations must not invent shapes or silently
accept arbitrary data for them. Partial models may cover only the explicitly
specified contract surface.

## SQLite migration decision

The proposed `2.0` schema reuses table names from the incompatible `1.0`
database. The implementation will not drop, rewrite, or auto-migrate existing
tables.

Pending choice:

- use `data/triage-v2.db` during rollout, then separately design migration; or
- approve a reviewed in-place `1.0` to `2.0` migration before the `2.0` CLI
  adopts `data/triage.db`.

Recommended rollout: use a versioned database first because canonical JSON and
the trace remain authoritative, and a fresh index is reversible.

## Invalid-run lifecycle decision

Sections 9.1 and 9.2 currently disagree. The state diagram transitions an
invalid physical run to `failed`, while the save sequence records a retryable
attempt with `agent_run.invalid` and indexes that attempt as failed.

Pending choice:

- make `invalid` a terminal physical-attempt outcome and allocate a new run ID
  for any retry; or
- require `agent_run.invalid` followed by `agent_run.failed` for every invalid
  response.

Recommended contract: `invalid` is terminal. It precisely describes why the
attempt ended, avoids a redundant event, and still permits a separately
identified retry.

## Blocked-review lifecycle decision

`ReviewRecord.report_status` permits `blocked`, but the investigation state
machine has no corresponding state. The workflow implementation therefore
does not invent a transition.

Pending choice:

- add an explicit `review_blocked` investigation state; or
- map a blocked review to the existing infrastructure-oriented `failed` state.

Recommended contract: add `review_blocked`. A sound review that refuses report
publication is materially different from a crashed or invalid investigation.

## Corpus accounting decision

The SQLite schema permits corpus membership values `included`, `excluded`, and
`unresolved`. The manifest summary and its reason rules currently cover only
included and excluded entries. Separately, the reviewer is described as
receiving terminal accounting for every corpus entry even though excluded
entries never enter the per-paper analysis state machine.

Recommended contract:

- retain all three membership states so unresolved discovery or identity work
  remains visible;
- define reviewer `expected`, `complete`, `unresolved`, and `failed` as
  accounting over included papers only;
- carry excluded and membership-unresolved totals separately in the reviewer
  task and rendered corpus accounting.

## Agent-behavior files requiring explicit approval

Any changes to the following are behavior changes and remain pending review:

- `AGENTS.md`
- `docs/schema.md`
- `docs/decisions.md`
- `docs/roles/orchestrator.md`
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
