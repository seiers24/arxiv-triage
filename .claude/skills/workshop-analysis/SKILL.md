---
name: workshop-analysis
description: Runs a complete accepted-paper analysis for one workshop on the shared investigation pipeline
---

# Workshop analysis

Use this component only from the main orchestrator. Follow the shared
`triage-topic` runbook and the base worker definitions. This overlay supplies
workshop-specific acquisition, reading, criticism, corpus review, and output
rules; it does not replace or weaken the shared evidence contracts.

## Required frozen inputs

Before dispatch, freeze and validate:

- a `WorkshopSpec` naming the `accepted` population and authoritative URL;
- the authoritative response and complete `WorkshopCorpusManifest`;
- an `InvestigationSpec`, `SearchPlan`, schema-2.0 `ObjectiveProfile`, and
  `WorkshopRankingPolicy`;
- one exact `PaperIdentity` and one source outcome for every listed entry;
- the exact component-skill hash used in every workshop worker task.

For EDGE CVPR 2026, use `objectives/edge-cvpr-2026.json` and
`objectives/edge-cvpr-2026-ranking-policy.json`. The objective is derived from
the frozen workshop CFP, not from model background knowledge.

## Procedure

1. Apply `references/acquisition.md`. Workshop membership is the complete
   authoritative accepted list; it may bypass semantic screening, but no
   listed entry may be omitted.
2. Resolve identities exactly and fetch sources in the declared precedence.
   Probable, ambiguous, or missing identities remain visible and never enter
   automatic paper analysis.
3. Materialize the questions in `references/reader-focus.md` into each
   `ReaderFocus.questions`, then dispatch the base paper reader.
4. Materialize the checks in `references/critic-rubric.md` into each
   `CriticRubric.checks`, then dispatch the base critic on the same source.
5. Close terminal accounting for all accepted entries. Do not equate identity
   resolution with completed analysis.
6. Apply the frozen ranking policy to canonical critic assessments. It selects
   every paper meeting the thresholds; it never fills a fixed top-k.
7. Materialize `references/reviewer-rubric.md` into
   `ReviewerRubric.checks`, dispatch exactly one base reviewer, and render only
   an accepted non-blocking review.
8. Apply `references/output-contract.md` to the deterministic workshop report.

## Hard boundaries

- Do not treat long-paper status, proceedings inclusion, peer review, or an
  award as technical evidence or a quality score.
- Do not let search results add workshop members.
- Do not treat modeled FLOPs, simulation, or desktop-GPU timing as on-device
  measurement.
- Do not let corpus-distinctiveness language enter a per-paper critic result.
  It is a qualitative reviewer inference supported by cross-paper references.
- Do not dispatch any worker unless its component instructions are embedded in
  the frozen task. A hash alone is provenance, not instructions.
- Do not start Phase 3 until the known-URL EDGE analysis completes end to end.

## Acceptance barrier

The known-URL run is complete only when all 15 accepted EDGE entries appear in
the output with one terminal state, all report claims resolve to
critic-supported evidence, the top tier reproduces from the frozen profile and
policy, and the reviewer accepts the report. Path B name-only discovery remains
a separate required test and must yield the identical membership set.
