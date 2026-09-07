# Agent Master File

Repository-wide instructions for AI agents. Directory-scoped `AGENTS.md` files
override this one where they exist — see the index at the bottom.

**Read `docs/README.md` first.** This file constrains; the documentation explains.
Where the two overlap, the documentation is the source of truth and this file
should link rather than restate — two copies drift, and the agent-facing copy is
always the unproofread one.

## What this repository is

`arxiv-triage` turns an arXiv query into a ranked, evidence-backed brief:
which papers matter for datacenter memory and AI infrastructure, what each one
actually claims, how strong the evidence is, and which are worth extending.

Every claim in the output carries an arXiv ID. Every LLM step leaves a trace.
Every failure is visible in the brief, never silently dropped.

## Instructions

### 1. Think and search before assuming
*Don't assume. Don't hide confusion. Surface tradeoffs.*

- State findings explicitly. A finding stays `unverified` until the critic has
  checked it against its source (see §3). Peer review is recorded as provenance,
  not treated as proof: arXiv preprints are the input to this tool, so "not peer
  reviewed" is the normal case, not a reason to discard.
- If multiple interpretations exist, present them. Do not pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear about the *task*, stop and ask the user. Name what is
  confusing. If something is unclear about a *paper*, dispatch a bounded
  investigation to a worker (§5) and record what came back, including "could
  not resolve."

### 2. Scripts do deterministic work; agents do judgment
- Fetching from arXiv, validating JSON, ranking, and writing the brief are
  scripts in `scripts/`. They never call a model. If a step can be done without
  a model, it must be.
- Agents read, extract, and critique. That is all. An agent that "calls the
  arXiv API" is a script wearing a costume; do not create one.
- When you are unsure which side a step belongs on, it is a script.

### 3. Claims and provenance
Every extracted claim is a record with:

| Field | Values |
|---|---|
| `status` | `unverified` → `supported` \| `unsupported` \| `overclaimed` |
| `evidence_type` | `simulation` \| `real_hardware` \| `theory` \| `none_stated` |
| `provenance` | `peer_reviewed` \| `preprint` \| `blog_or_docs` \| `inferred` |
| `source_span` | the quoted text the claim rests on, or `null` |

Rules:
- A claim with `source_span: null` cannot be `supported`.
- `evidence_type` must match the source. A simulation result described as
  measured is `overclaimed`, not a nitpick.
- `inferred` provenance means the agent reasoned it; it is never cited as if the
  paper said it.

### 4. Bounded loops, visible failure
- One critic pass per paper. On `unsupported` or `overclaimed`, one re-read by
  the reader. Then the record is marked `unresolved` and surfaced in the brief
  under its own heading.
- No agent retries itself more than once. No loop without a counter.
- A crash, a schema-validation failure, or a missing paper is logged and
  reported, never swallowed. The brief prints the count of unresolved and
  failed papers at the top.

### 5. Roles
There is one orchestrator and two workers. The hierarchy is one level deep.

| Role | What it is | Input → Output | Definition |
|---|---|---|---|
| **Orchestrator** | The main session reading this file | a topic → the brief | this file + `.claude/skills/triage-topic/SKILL.md` |
| **paper-reader** | Worker | one arXiv ID → one schema record | `.claude/agents/paper-reader.md` |
| **critic** | Adversarial worker | one record + its source → per-claim verdicts | `.claude/agents/critic.md` |

- The orchestrator dispatches, collects, and decides. It does not read papers
  itself and does not rewrite worker output.
- Workers return the schema and nothing else. No prose, no summaries outside
  the fields, no opinions on ranking.
- The critic gets the record and the source text. It does not get the reader's
  reasoning, so it cannot be anchored by it.

### 6. Workflow (in order; the skill file is the runbook)
1. `scripts/fetch.py <query>` → `data/papers.json`
2. For each paper: dispatch `paper-reader` → `data/records/<id>.json`
3. `scripts/validate.py` on each record; reject malformed, log, retry once
4. For each valid record: dispatch `critic` → `data/verdicts/<id>.json`
5. Apply §4: re-read on failure, then mark `unresolved`
6. `scripts/rank.py` → `out/brief.md` with arXiv IDs on every claim
7. Append one line per dispatch to `logs/trace.jsonl`
   (`paper_id, role, timestamp, validation_pass, retry_count, verdict_summary`)

### 7. Output contract
The schema in `docs/schema.md` is the contract between every script and every
agent. Change it there first; then the Pydantic model in `scripts/validate.py`;
then the agent definitions. Never change it in an agent prompt alone.

### 8. Do not
- Do not build a UI, a vector store, a knowledge graph, or a Docker image.
  They are listed in `docs/README.md` as next steps; that is where they stay.
- Do not add a third worker without adding a row to §5 and a reason to
  `docs/decisions.md`.
- Do not present a ranked brief without the unresolved-and-failed count.
- Do not cite anything you did not fetch.

## Working with this repo
- Python ≥ 3.12, `uv` for everything. `uv run scripts/<name>.py`.
- Secrets in `.env` only, never in files that are committed.
- Model calls, if any are made from Python, log token counts and cost to the
  same `logs/trace.jsonl`.
- Design decisions go in `docs/decisions.md` with the alternative considered.

## Index of directory-scoped AGENTS.md
None yet. Add a row here when you add one.

| Path | Scope |
|---|---|
| | |
