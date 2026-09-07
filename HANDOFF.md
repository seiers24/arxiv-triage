# HANDOFF — arxiv-triage

Briefing for an agent or person picking this repo up cold. Written 2026-09-06.

`AGENTS.md` is the binding contract and Codex reads it natively. This file is
orientation: what the project is, why it exists, what is built, and what to do
next. Where the two disagree, `AGENTS.md` wins.

---

## 1. What this is

`arxiv-triage` turns an arXiv query into a ranked, evidence-backed brief:
which papers matter for datacenter memory and AI infrastructure, what each one
actually claims, how strong the evidence is, and which are worth extending.

The system under construction is deliberately **one small piece proven well**,
not a platform. The piece is a single function:

> one arXiv paper in → a relevance and importance judgment out, with quoted
> source spans and a version stamp

Everything else in the repo exists to make that one function auditable and
measurably improvable. Other pieces (an adversarial verification stage, cross-run
memory, retrieval) are downstream consumers of its output, not part of it.

## 2. Why it exists

It is a rehearsal. A research take-home is expected on 2026-09-08 or 09-09 for an
internship on a team that builds an internal multi-agent research platform over
arXiv literature. The assignment is expected to be one of: build a pipeline,
critique a paper and propose extensions, or design an architecture with an
evaluation plan. This repo is the artifact that makes all three cheaper to
answer, and it is meant to be forkable on the day the assignment lands.

Practical consequences for anyone working here:

- **Small and finished beats large and described.** A working seven-step run with
  an honest limitations section is the goal. Breadth is not.
- **Every design decision must be defensible out loud, without notes.** Do not
  add machinery whose rationale is "the framework does it this way."
- **Deadline pressure is real.** Decision expected by 2026-09-12.

`micronresearchassignmentstudyplan.md` in this directory is personal prep and is
gitignored. It is not part of the project and does not need reading.

## 3. Architecture in one screen

```
  query ──► scripts/fetch.py ──► data/papers.json          (no model)
                                      │
              Orchestrator (main agent session, follows the skill runbook)
                     │                          │
                     ▼                          ▼
             paper-reader subagent        critic subagent      (one level deep)
                     │                          │
             data/records/<id>.md       data/verdicts/<id>.json
                     └──────────┬───────────────┘
                                ▼
                     scripts/db.py ingest        (the only writer to SQLite)
                                │
                     data/triage.db ──► scripts/rank.py ──► out/brief.md
```

Seven steps, in order:

| # | Step | Who | Model? |
|---|---|---|---|
| 1 | Query arXiv, save 10–15 papers with abstracts | `scripts/fetch.py` | no |
| 2 | Per paper: extract one record (problem, method, claims with spans, evidence type, relevance, importance, extendability) | `paper-reader` | yes |
| 3 | Validate and store the record | `scripts/db.py ingest` | no |
| 4 | Per record: verdict per claim — supported / unsupported / overclaimed | `critic` | yes |
| 5 | On a bad verdict: one re-read, then mark unresolved and surface it | orchestrator | — |
| 6 | Rank and write the brief | `scripts/rank.py` | no |
| 7 | Trace: every dispatch is a row in `runs` | `scripts/db.py` | no |

## 4. Decisions already made — do not relitigate

These are settled. If you think one is wrong, say so in `docs/decisions.md` with
the alternative; do not silently change the code.

1. **Scripts do deterministic work; agents do judgment.** Fetching, validating,
   ranking, and database writes never call a model. An agent that "calls the
   arXiv API" is a script wearing a costume.
2. **One orchestrator, two workers, one level deep.** No nesting, no third
   worker without a decision entry.
3. **The critic is isolated from the reader.** It sees the record and the source
   text, never the reader's reasoning, so it cannot be anchored by it. The critic
   also never edits the reader's prompt; its only influence is through numbers a
   human reads.
4. **Runs are append-only.** A re-read is a new run with a new id, never an
   update. The `runs` table is the trace; there is no separate JSONL log.
5. **A path locates, a hash proves.** Markdown artifacts live on disk; the
   database stores both the path and the SHA-256.
6. **A version is the agent definition file hash plus the model id.** Editing
   `.claude/agents/paper-reader.md` creates a new version automatically. Nothing
   is compared across versions without that stamp.
7. **Bounded loops, visible failure.** One critic pass, one re-read, then
   `unresolved`. The brief prints the unresolved and failed count at the top.
8. **Abstracts only, not full PDFs**, for now. Stated as a limitation, not hidden.

## 5. Current state — accurate as of this writing

| Component | State |
|---|---|
| `AGENTS.md` contract | done |
| `README.md` | done |
| `scripts/db.py` (schema, `init`, `ingest`) | done, smoke-tested |
| `data/triage.db` | initialized, empty, gitignored |
| `.claude/agents/paper-reader.md` | started, roughly a third written |
| `docs/schema.md` | **empty** — the contract lives only in code right now |
| `docs/decisions.md` | **empty** |
| `docs/evaluation.md` | **empty** |
| `scripts/fetch.py` | not started |
| `scripts/rank.py` | not started |
| `.claude/agents/critic.md` | not started |
| `.claude/skills/triage-topic/SKILL.md` (runbook) | not started |
| `eval/golden.jsonl` + `scripts/score.py` | not started |
| End-to-end run on one query | **not yet** |

`main.py` is leftover `uv init` scaffolding and can be deleted.

## 6. The artifact contract, as enforced today by `scripts/db.py`

`docs/schema.md` is empty, so this section is currently the only written copy.
**Task one is to move it into `docs/schema.md` and delete it from here** before
the two drift.

Agents write a markdown file for humans containing exactly one fenced `json`
block for the machine. A plain `.json` file is also accepted.

Reader artifact:

```json
{
  "role": "reader",
  "arxiv_id": "2403.14123",
  "relevance": 5,
  "importance": 5,
  "extendable": true,
  "reason": "one line, why this score",
  "claims": [
    {
      "text": "the claim in the agent's words",
      "source_span": "verbatim quote from the abstract, or null",
      "evidence_type": "simulation | real_hardware | theory | none_stated",
      "provenance": "peer_reviewed | preprint | blog_or_docs | inferred"
    }
  ]
}
```

Critic artifact:

```json
{
  "role": "critic",
  "arxiv_id": "2403.14123",
  "reader_run_id": "r-6172fd4d638e",
  "verdicts": [
    {"claim_index": 0, "status": "supported", "reason": "span matches the abstract"},
    {"claim_index": 1, "status": "unsupported", "reason": "no source span"}
  ]
}
```

Rules the code enforces: enum values must match exactly; a critic verdict must
reference a claim belonging to the named reader run; re-ingesting an identical
file returns the existing run id instead of duplicating; any failure rolls the
whole transaction back, so no partial run rows are ever left behind.

Rules the code does **not** yet enforce, and should: a claim with
`source_span: null` cannot be `supported`, and `evidence_type` must match what
the source actually says. Both are written in `AGENTS.md` §3.

## 7. Database

Six tables in `data/triage.db`: `papers`, `runs`, `claims`, `scores`,
`verdicts`, `labels`. `runs` is the trace. `labels` holds hand labels for the
golden set, which makes the improvement loop one join.

```bash
uv run scripts/db.py init
uv run scripts/db.py ingest data/records/2403.14123.md --model claude-opus-5
```

`--allow-new-paper` inserts a stub paper row when `fetch.py` has not run yet;
without it, an unknown paper is a hard error.

The improvement loop is this query, grouped by reader version:

```sql
SELECT r.version,
       COUNT(DISTINCT s.run_id) AS papers_scored,
       ROUND(AVG(s.relevance), 2) AS avg_relevance,
       ROUND(100.0 * SUM(v.status = 'supported') / COUNT(v.status), 1) AS support_rate_pct
FROM runs r
JOIN scores s  ON s.run_id = r.run_id
JOIN claims cl ON cl.run_id = r.run_id
LEFT JOIN verdicts v ON v.claim_id = cl.claim_id
WHERE r.role = 'reader'
GROUP BY r.version;
```

A reader version that lowers agreement against `labels` does not ship, whatever
else it improves.

## 8. Build order — do these in sequence

1. `docs/schema.md` from §6 above, then delete §6 from this file
2. `scripts/fetch.py` — arXiv API query → `data/papers.json` → insert `papers` rows
3. Finish `.claude/agents/paper-reader.md` to emit exactly the reader artifact
4. `.claude/agents/critic.md`
5. `.claude/skills/triage-topic/SKILL.md` — the runbook the orchestrator follows
6. `scripts/rank.py` → `out/brief.md`
7. First end-to-end run on one query; update the state table in `README.md`
8. `docs/decisions.md` and `docs/evaluation.md`
9. `eval/golden.jsonl` (20–30 hand-labeled papers) and `scripts/score.py`

Definition of done: steps 1–7 of the pipeline run on one query without
intervention, every claim in the brief carries an arXiv ID, the unresolved count
is at the top, and `runs` has one row per dispatch.

## 9. Out of scope — do not build

No UI, no vector store, no knowledge graph, no Docker, no ORM, no migrations
framework, no third worker, no full-PDF reading, no LangGraph wiring. Each is one
line under "next steps" in `README.md` and nothing more. LangGraph and the Claude
Agent SDK are named there as the productization path; naming them is the whole
requirement.

`pyproject.toml` currently lists langgraph, langchain, and openai packages from
an early `uv init`. Nothing imports them. Leave them or prune them, but do not
start using them.

## 10. Environment

Python 3.12+ via `uv` (`uv sync`, `uv run`). `scripts/db.py` is standard library
only, and keeping it that way is deliberate. No API key is required: the model
steps run as subagents inside the harness. If someone later adds direct API
calls, the key goes in `.env`, which is gitignored, and token counts and cost go
into the `runs` row.

Gitignored: `.env`, `data/triage.db`, `micronresearchassignmentstudyplan.md`,
plus the usual Python artifacts. Nothing is committed yet; the repo has no
commits.

## 11. Open questions

- Should `rank.py` rank by relevance, importance, or a combination? Not decided.
  Whatever is chosen goes in `docs/decisions.md` with the alternative.
- How many papers per run is right? 10–15 is a guess, not a measurement.
- The critic checks claims against the abstract only, so a claim the abstract
  itself overstates relative to the paper body will pass. Known and accepted for
  now; it belongs in the limitations section of any writeup.
