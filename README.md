# arxiv-triage

`arxiv-triage` turns a frozen research objective and paper corpus into a
ranked, evidence-backed brief. The objective controls relevance and ranking;
it never changes whether the source supports a claim.

Every displayed claim resolves to exact frozen source bytes. Every model
attempt leaves an append-only trace. Screening decisions, degraded source
fallbacks, unresolved objections, and failures remain visible.

## Status

The shared schema-2.0 investigation pipeline is implemented through the
network-free three-paper acceptance fixture:

- closed screening, reader, critic, reviewer, run, and terminal-state contracts;
- immutable artifact storage, lifecycle trace, reconciliation, and rebuildable
  SQLite index;
- exact-version arXiv HTML/PDF/abstract source fallback;
- deterministic ranking and report/CSV/human-review rendering;
- thin workflow, acquisition, ranking, rendering, reconciliation, and rebuild
  commands.

The workshop-analysis component and its full EDGE 2026 acceptance run are the
next delivery gate. Phase 3 proposal-relevance work remains blocked until that
workshop run succeeds end to end.

## Verification

Requirements are Python 3.12+ and
[uv](https://docs.astral.sh/uv/). Core tests make no network calls.

```bash
uv sync --frozen
PYTHONPATH=src uv run --with pytest pytest tests -q
```

The executable runbook is `.claude/skills/triage-topic/SKILL.md`. Its current
deterministic command surface begins with:

```bash
uv run scripts/workflow.py create --spec <path> --profile <path> --search-plan <path>
uv run scripts/workflow.py status <investigation-id>
uv run scripts/workflow.py freeze-candidates <investigation-id> \
  --candidate-set <path> --screening-scope <path> --search-complete
uv run scripts/workflow.py prepare-screening <investigation-id> --batch-size <n>
uv run scripts/workflow.py accept-run --task <path> --raw-output <path> --model <model>
uv run scripts/workflow.py freeze-corpus <investigation-id> \
  --mode <semantic|authoritative> --frozen-at <timestamp>
uv run scripts/fetch_source.py <candidate-or-identity-path>
uv run scripts/rank.py <investigation-id>
uv run scripts/render.py <investigation-id>
uv run scripts/reconcile.py <investigation-id>
uv run scripts/db.py rebuild
```

Workers are dispatched by the main orchestrator after deterministic task
preparation. They do not fetch, run scripts, invoke other agents, persist
canonical records, or rank papers.

## Architecture

```text
frozen candidates -> screening/bypass -> immutable corpus
                                             |
                 exact frozen source -> reader -> critic -> terminal paper state
                                             |                    |
                                             +--------------------+
                                                                  v
all corpus entries and terminal paper records -> corpus reviewer -> rank/render
                                                                  |
                                          canonical JSON + trace -> SQLite index
```

JSON artifacts and JSONL trace events are authoritative. SQLite is only a
query projection and can be deleted and rebuilt from those artifacts.

## Documentation

Start with `docs/README.md`. The canonical references are:

- `docs/schema.md` — serialized contracts and validation rules;
- `docs/decisions.md` — accepted design decisions and tradeoffs;
- `docs/specs/01-core-investigation-platform.md` — shared implementation spec;
- `docs/plans/02-workshop-analysis.md` — workshop component and EDGE acceptance;
- `docs/roles/orchestrator.md` — orchestrator authority and boundaries;
- `docs/evaluation.md` — offline human evaluation procedure.

Deferred work includes proposal relevance, open-ended latest-developments
analysis, vector search, a knowledge graph, UI, and a workflow framework.
