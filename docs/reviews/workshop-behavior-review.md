# Workshop behavior review

**Status:** W1-W5 approved for implementation and worker dispatch on 2026-09-14

**Created:** 2026-09-13

This records the completed Phase 2 behavior review. W1-W5 are approved; the
exact overlay bundle must be hashed and embedded in worker tasks before EDGE
reader, critic, or reviewer dispatch.

## Proposed behavior

### W1 — One shared reader contract

The workshop reader uses the existing minimal `ReaderRecord`. Eight ordered
focus questions ask for CFP topic, efficiency mechanism, training/inference
scope, baselines, metrics, numeric results, tradeoffs, execution environment,
limitations, assumptions, and facts that ground a testable extension. Answers
remain ordinary source-bound claims; there are no workshop-only reader fields.

### W2 — Embedded critic and reviewer instructions

Add ordered `checks` to `CriticRubric` and `ReviewerRubric`. A skill hash proves
which overlay version was selected but cannot tell a tool-free worker what to
do. Embedding the exact checks in each self-hashed task makes the behavior both
available and auditable. Empty checks remain valid for components that need no
overlay.

The critic checks evidence modality, actual hardware conditions, baseline/
metric/scope preservation, missing evaluation, literal objective anchors, and
human-review triggers. It does not make corpus-wide distinctiveness judgments.

The reviewer checks exact 15-paper accounting, deterministic top-tier
arithmetic, cross-paper claims, track-neutral treatment, exclusions caused by
unresolved evidence, and separation of paper advertising from supported facts
and reviewer inference.

### W3 — Smaller accounting surface

The workshop manifest records only `declared`, `extracted`, `resolved`, and
`identity_unresolved`. It does not duplicate `complete`,
`analysis_unresolved`, or `failed`; those already belong to the shared corpus
and paper-state contracts. This also avoids calling not-yet-analyzed papers
"unresolved" immediately after extraction.

### W4 — Anchored objective and no fixed top-k

The proposed EDGE objective has five paper-local 0-through-5 dimensions:

- workshop fit, weight 2 and an objective gate;
- evidence strength, weight 2;
- efficiency result, weight 2;
- deployment realism, weight 1.5;
- extension leverage, weight 1.5.

Corpus distinctiveness remains a qualitative, cross-paper reviewer finding.
It is not a sixth critic score, because a per-paper critic never sees the full
corpus and the base reviewer contract does not need another numeric output.

The proposed top-tier rule requires weighted mean at least 4.0, workshop fit at
least 4, evidence strength at least 3, efficiency result at least 3, deployment
realism at least 2, extension leverage at least 2, and no unresolved
uncertainty. Every paper meeting the rule qualifies; none are added to fill a
quota.

### W5 — Exact source and report boundaries

The source hierarchy is exact-version arXiv HTML, arXiv PDF, official
proceedings PDF, exact OpenReview PDF, then an explicit abstract-only fallback.
An external PDF URL must already be bound to a `resolved_exact` identity.

The report must show all 15 accepted papers once, retain identity/source/
analysis failures, cite supported claims for factual and relevance statements,
display top-tier threshold failures, and label corpus distinctiveness and
extensions as inference. Long/short track and proceedings inclusion are
provenance, not quality evidence.

## Files in the proposed behavior diff

- `.claude/skills/workshop-analysis/SKILL.md`
- `.claude/skills/workshop-analysis/references/acquisition.md`
- `.claude/skills/workshop-analysis/references/reader-focus.md`
- `.claude/skills/workshop-analysis/references/critic-rubric.md`
- `.claude/skills/workshop-analysis/references/reviewer-rubric.md`
- `.claude/skills/workshop-analysis/references/output-contract.md`
- `.claude/agents/critic.md`
- `.claude/agents/reviewer.md`
- `objectives/edge-cvpr-2026.json`
- `objectives/edge-cvpr-2026-ranking-policy.json`

The exact overlay bundle is hashed and materialized into worker task inputs
before the known-URL 15-paper run. Phase 3 remains blocked until that run
completes end to end.
