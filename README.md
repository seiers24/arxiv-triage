# arxiv-triage

Turns an arXiv query into a ranked, evidence-backed brief: which papers matter
for datacenter memory and AI infrastructure, what each one actually claims, how
strong the evidence is, and which are worth extending.

Every claim carries an arXiv ID. Every model step leaves a trace. Every failure
is visible in the brief, never dropped.

## Status

| Component | State |
|---|---|
| `AGENTS.md` contract, folder layout | done |
| `docs/schema.md` + `scripts/validate.py` | not started |
| `scripts/fetch.py` | done — deterministic arXiv fetch, frozen inputs, SQLite upsert, offline fixture |
| `.claude/agents/paper-reader.md` | done — full-text-first reader contract |
| `.claude/agents/critic.md` | not started |
| `.claude/skills/triage-topic/SKILL.md` runbook | not started |
| `scripts/rank.py` | not started |
| `docs/decisions.md`, `docs/evaluation.md` | not started |
| End-to-end run on one query | not yet |

Update this table as pieces land. It is the honest answer to "does it work."

## Quickstart

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/), and Claude Code.
No API key is needed; the model steps run as Claude Code subagents.

```bash
uv sync
uv run scripts/fetch.py "KV cache compression"
```

Then, inside Claude Code in this directory:

```
/triage-topic
```

The orchestrator follows the runbook in `.claude/skills/triage-topic/SKILL.md`
and writes `out/brief.md`. Watch `logs/trace.jsonl` for one line per dispatch.

## What it does

**Input:** one arXiv search query.

**Output:** `out/brief.md`. Papers ranked by relevance to datacenter memory and
AI infrastructure. Every claim has an arXiv ID and a verdict. The first line
states how many papers were unresolved or failed.

**The seven steps:**

| # | Step | Who | Model? |
|---|---|---|---|
| 1 | Query arXiv, save 10–15 papers with abstracts to `data/papers.json` | `scripts/fetch.py` | no |
| 2 | Per paper: extract one JSON record (problem, method, claims with quoted spans, evidence type, relevance, extendability) | `paper-reader` subagent | yes |
| 3 | Validate each record against the schema; one retry, then log as failed | `scripts/validate.py` | no |
| 4 | Per valid record: verdict on each claim, `supported` / `unsupported` / `overclaimed` | `critic` subagent | yes |
| 5 | On a bad verdict: one re-read, then mark `unresolved` and surface it | orchestrator | — |
| 6 | Rank and write the brief | `scripts/rank.py` | no |
| 7 | Append one trace line per dispatch to `logs/trace.jsonl` | orchestrator | — |

## Architecture

```
                     ┌──────────────────────────┐
  query ──► fetch.py ──► data/papers.json        │
                     │                          │
                     │   Orchestrator            │  (main Claude Code session,
                     │   follows SKILL.md        │   reads AGENTS.md)
                     │      │            │       │
                     │      ▼            ▼       │
                     │  paper-reader   critic    │  (subagents, one level deep)
                     │      │            │       │
                     │  data/records  data/verdicts
                     └──────┬───────────┬────────┘
                            ▼           ▼
                        validate.py   rank.py ──► out/brief.md
                                                  logs/trace.jsonl
```

Three rules shape it:

1. **Scripts do deterministic work; agents do judgment.** Fetching, validating,
   and ranking never touch a model. Only reading, extraction, and critique do.
2. **One level deep.** One orchestrator, two workers, no nesting. Easy to trace,
   cheap to evaluate.
3. **The critic is isolated.** It sees the record and the source, not the
   reader's reasoning, so it cannot be anchored by it.

Full rationale with alternatives considered: `docs/decisions.md`.

## The claim record

Each extracted claim carries:

| Field | Values |
|---|---|
| `status` | `unverified` → `supported` \| `unsupported` \| `overclaimed` \| `unresolved` |
| `evidence_type` | `simulation` \| `real_hardware` \| `theory` \| `none_stated` |
| `provenance` | `peer_reviewed` \| `preprint` \| `blog_or_docs` \| `inferred` |
| `source_span` | quoted text the claim rests on, or `null` |

A claim with no source span cannot be `supported`. A simulation result described
as measured is `overclaimed`. Full schema: `docs/schema.md`.

## Reliability

- Bounded loops: one critic pass, one re-read, then `unresolved`. No agent
  retries itself more than once.
- Schema validation between every agent and every script.
- Failures are counted at the top of the brief, not hidden in a log.

## Evaluation

How output quality is checked, including a small hand-labeled set for critic
accuracy: `docs/evaluation.md`.

## Layout

```
AGENTS.md            contract every agent reads (CLAUDE.md imports it)
docs/                README, schema, decisions, evaluation
scripts/             fetch.py, validate.py, rank.py   (no model calls)
.claude/agents/      paper-reader.md, critic.md
.claude/skills/      triage-topic/SKILL.md            (the runbook)
data/                papers.json, records/, verdicts/
out/                 brief.md
logs/                trace.jsonl
```

## Limitations

- Reads abstracts only, not full PDFs.
- Relevance scoring is a model judgment with a one-line reason, not a
  calibrated metric.
- The critic checks claims against the abstract, so a claim the abstract
  overstates relative to the paper body will pass.
- Single query, single run. No memory across runs.

## Next steps (deliberately not built)

- Full-PDF reading with span-level citations
- Vector store for retrieval across runs
- Knowledge graph of techniques, claims, and hardware assumptions
- Productization outside Claude Code (LangGraph or the Claude Agent SDK)
- Golden set large enough to report critic precision and recall

## How I worked

Claude Code was used as the orchestrator harness and as a coding assistant for
scaffolding and docs. The architecture, the schema, the reliability rules, and
every design decision in `docs/decisions.md` are mine and I can defend each one
without notes. Model-generated code was reviewed and run before being kept.
