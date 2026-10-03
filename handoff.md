# arxiv-triage Phase 2 handoff

Updated: 2026-09-14

Repository: `/home/zenithblade/workspace/arxiv-triage`

Branch: `main`

## Read first

Read `docs/README.md`, root `AGENTS.md`, `docs/schema.md`,
`docs/decisions.md`, `docs/roles/orchestrator.md`,
`.claude/skills/triage-topic/SKILL.md`, and the complete
`.claude/skills/workshop-analysis/` component before acting. Repository
documentation is authoritative.

## Hard gate

Phase 3 must not start until a complete known-URL EDGE workshop analysis runs
end to end and the corpus reviewer accepts a renderable report. That gate has
not passed. Do not implement Phase 3.

## Phase 1

Phase 1 is complete. The schema-2.0 screening, source, reader, critic,
reviewer, run-lifecycle, persistence, reconciliation, ranking, rendering, and
database paths are implemented and covered by the current test suite.

## Phase 2 implementation status

The user approved workshop behavior gates W1-W5 on 2026-09-14. The approved
component bundle is materialized at:

`data/workshops/edge-cvpr-2026/overlays/c0153bc150cbea740a8c2e3f1c8fa1c40aa48151bcafc78461e968a92cfa1020/`

Implemented Phase 2 pieces include:

- exact known-URL accepted-paper extraction;
- exact CVF, arXiv, and curated OpenReview identity resolution;
- workshop-to-Core candidate adaptation with authoritative membership;
- bounded exact source acquisition and immutable source reconciliation;
- shared-contract reader, critic, and reviewer overlays;
- deterministic workshop ranking and threshold-based top-tier classification;
- workshop report metadata, score/evidence matrices, inference labels, and
  provenance support;
- source-file freezing for already-downloaded exact PDFs;
- terminal paper-state recovery from validated critic run artifacts.

The workshop ranking artifact now embeds the complete validated
`WorkshopRankingPolicy`, not only its hash, so a tool-free reviewer can
reproduce top-tier flags. Future accepted runs also copy component skill hashes
from each frozen focus/rubric into run and trace provenance.

## Frozen EDGE corpus and sources

The authoritative EDGE CVPR 2026 corpus is frozen at 15 accepted papers:

- declared: 15
- extracted: 15
- identity resolved: 15
- Core discovered/included: 15/15
- source ready: 15/15

`data/workshops/edge-cvpr-2026/source-acquisition.json` preserves the original
13 successes and two OpenReview HTTP failures. The two exact PDFs were later
acquired through the browser and frozen. The non-destructive follow-up artifact
`data/workshops/edge-cvpr-2026/source-readiness.json` validates every original
and normalized byte hash and reports `ready=15`, `not_ready=0`.

## Live acceptance attempt

Investigation: `inv-edge-cvpr-2026`

The run produced and validated:

- 15 canonical `ReaderRecord` artifacts;
- 15 canonical `CriticRecord` artifacts;
- paper accounting: 3 `complete`, 12 `analysis_unresolved`, 0 `failed`;
- one deterministic ranking over all 15 papers;
- one canonical `ReviewRecord`.

Reader lifecycle history includes one no-output attempt, one invalid evidence
modality, and one invalid quote locator. Each raw invalid attempt remains in
its run directory; the permitted attempt-two records validated. All 15 critic
attempts validated on attempt one.

The reviewer returned a valid `blocked` decision with 13 challenges and 13
human-review items. Twelve concern material paper-level uncertainty. The
thirteenth identified that the frozen reviewer task had only the ranking
policy hash and could not reproduce the thresholds. The latter integration
defect is fixed in code for a future separately identified run, but the valid
blocked result and its inputs were not rewritten.

Current status:

```text
inv-edge-cvpr-2026 = review_blocked
```

Rendering was explicitly attempted and correctly refused with `a blocked
review cannot be rendered`. No report exists for this investigation.

The blocked-review decision is not automatically resumable. The approved
design says a later explicit resolution workflow is required, and none is
defined. Do not invent one or dispatch a second logical reviewer job in the
same investigation.

## Live-run provenance caveat

The live reader/critic/reviewer tasks contain the approved component skill hash,
but their trace events have `component_skill_hash: null` because the CLI did
not copy it into `RunContext`. This was fixed after the run. Historical trace
events were not rewritten. Together with the blocked review, this means the
current investigation is diagnostic evidence, not the passing Phase 2
acceptance run.

## Verification

Current network-free suite:

```text
142 passed, 7 subtests passed
```

Command:

```bash
PYTHONPATH=src UV_CACHE_DIR=/tmp/arxiv-triage-uv-cache \
  uv run --offline --with pytest pytest -q tests
```

SQLite was rebuilt from validated artifacts. Reconciliation for
`inv-edge-cvpr-2026` reports no interrupted runs, no reindex requirements, no
integrity errors, and `clean=true`.

## Next decision

Discuss the 12 substantive human-review challenges with the user before any
new acceptance run. A new run may use the now-embedded ranking policy and fixed
skill-hash provenance, but changing critic/reviewer behavior or weakening the
blocked-review rule requires an explicit design decision and the normal review
protocol. Do not tune worker outputs merely to make the acceptance test pass.

## Repository hygiene

The worktree is intentionally dirty with Phase 2 implementation and data
artifacts. Preserve unrelated changes. Do not remove the pre-existing tracked
`.DS_Store` files. Do not commit unless the user asks.
