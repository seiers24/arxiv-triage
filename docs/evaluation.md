# Evaluation

This document defines how maintainers and human reviewers evaluate
`arxiv-triage`. It is not a runtime prompt and must not be supplied to the
paper-reader or critic. Objective-specific domain priorities belong in
`objectives/*.json`; role instructions belong in the corresponding agent
definition.

Evaluation answers four questions:

1. Does the pipeline preserve inputs, validate artifacts, and expose failures?
2. Does the reader extract faithful, well-grounded claims?
3. Does the critic identify unsupported or overclaimed claims?
4. Does each objective profile produce a useful ranking for its stated purpose?

## Evaluation set

Begin with 5–10 frozen papers. Include clearly relevant, borderline, and
irrelevant papers, with a mix of simulation, real-hardware, theory, and
unstated evidence where available. Store the exact paper records and input
hashes under `evaluation/papers/`.

Human labels are stored separately from agent inputs:

```text
evaluation/
  papers/                         frozen paper records
  golden/universal/               objective-independent labels
  golden/<objective-id>/          objective-specific labels
  reports/                        generated evaluation results
```

Never include golden labels in a reader or critic dispatch.

### Universal human labels

For each paper, record:

- Important paper-stated claims that a useful summary should capture.
- The exact supporting abstract span for each claim.
- The correct evidence type and provenance.
- Supported, unsupported, or overclaimed verdicts for evaluated claims.

### Objective-specific human labels

For each paper and objective profile, record:

- Expected objective relevance (`0`–`5`).
- Expected relevance category or `null`.
- Expected technical importance (`0`–`5`).
- Whether a useful, objective-aligned extension exists.
- Whether the paper belongs in the objective's priority set.
- A short justification for each judgment.

Scores are ordinal judgments, not physical measurements. A system score within
one point of the human label counts as agreement. Rankings from different
objective hashes are evaluated separately and are never compared directly.

## Procedure

1. Freeze the evaluation papers, objective profile, schema, agent definitions,
   model IDs, and their hashes.
2. Create or approve the human labels before inspecting the evaluated run.
3. Run the normal pipeline without exposing golden labels to either worker.
4. Preserve every output, failed attempt, retry, trace event, and terminal state.
5. Compare validated artifacts with the labels using deterministic code where
   possible. Mark semantic claim matches for human review rather than guessing
   them in a script.
6. Write a dated report under `evaluation/reports/` containing raw counts,
   rates, disagreements, runtime, token usage, and cost.

If reviewers disagree, retain both judgments and record the adjudicated label
with a short reason. Do not silently alter labels to improve the result.

## Criteria

### 1. Contract and reliability

| Criterion | Measurement | Initial acceptance criterion |
|---|---|---:|
| Terminal-state coverage | Fetched papers ending as `complete`, `unresolved`, or `failed` / fetched papers | 100% |
| Exact-span validity | Non-null source spans passing canonical substring validation / non-null spans | 100% |
| Schema validity after retry | Reader and critic artifacts valid after allowed retries / expected artifacts | at least 90% |
| Critic claim coverage | Valid critic outputs with exactly one verdict per reader claim | 100% |
| Artifact integrity | Referenced artifacts whose hashes match their trace and index entries | 100% |
| Deterministic ranking | Repeated ranking from identical artifacts and objective hash | byte-identical |
| Visible failure | Failed or unresolved papers represented in the brief | 100% |

Always report the first-attempt schema-valid rate separately; retries must not
hide brittle agent output.

### 2. Reader quality

| Criterion | Measurement | Initial acceptance criterion |
|---|---|---:|
| Claim faithfulness | Human-supported reader claims / evaluated paper-stated reader claims | at least 90% |
| Important-claim coverage | Human-labeled important claims represented by a faithful reader claim | at least 80% |
| Evidence-type accuracy | Reader claims with the human-labeled evidence type / evaluated claims | at least 90% |
| Provenance accuracy | Reader claims with the human-labeled provenance / evaluated claims | 100% |

Report raw numerators and denominators because percentages from a small set can
be misleading.

### 3. Critic quality

| Criterion | Measurement | Initial acceptance criterion |
|---|---|---:|
| Verdict accuracy | Critic verdicts matching adjudicated human verdicts / evaluated verdicts | at least 90% |
| Bad-claim recall | Human-labeled unsupported or overclaimed claims rejected by the critic / all such claims | 100% on planted cases |
| False rejection rate | Human-supported claims rejected by the critic / human-supported claims | report; target at most 10% |
| Relevance-chain check | Incorrect objective-relevance chains rejected / planted incorrect chains | 100% on planted cases |

Include at least one deliberately unsupported claim, one overclaimed claim, and
one unjustified objective-relevance chain. Label these as planted evaluation
cases; do not mix them into claims about natural error rates.

### 4. Objective and ranking quality

Evaluate each objective hash independently.

| Criterion | Measurement | Initial acceptance criterion |
|---|---|---:|
| Relevance agreement | System relevance within one point of the human label | at least 80% |
| Category accuracy | System category matching the human label | at least 80% |
| Importance agreement | System importance within one point of the human label | at least 80% |
| Top-k precision | Human-priority papers in the system's top `k` / `k` | at least 80% |
| Ranking-policy accuracy | Reported scores and tie-breaks matching the selected profile | 100% |

Choose `k` before running the evaluation and keep it no larger than the number
of human-priority papers. A critic-rejected load-bearing claim must trigger the
documented review gate regardless of its numeric score.

## Reader-versus-critic comparison

On the same frozen papers, compare reader-only output with reader-plus-critic
output. Report:

- Unsupported or overclaimed statements that would reach the brief.
- Correct claims incorrectly blocked.
- Papers moved to `unresolved` or `needs_review`.
- Added wall time, model calls, tokens, and cost.

This comparison measures whether the critic's quality improvement justifies its
cost; the critic's value is not assumed.

## Reporting limitations

- Abstract-only validation does not establish full-paper correctness, novelty,
  or reproducibility.
- Exact quotation proves source location, not scientific truth.
- Reader and critic errors may be correlated, especially when they use the same
  model family.
- Technical importance and objective relevance remain human judgments even
  when the ranking calculation is deterministic.
- Initial thresholds are demonstration gates, not statistically reliable
  performance claims. Revisit them only through a recorded design decision,
  never after inspecting a result merely to make a run pass.
