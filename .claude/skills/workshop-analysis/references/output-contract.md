# Workshop output contract

The deterministic renderer produces a complete accepted-paper CSV and Markdown
table, source-resolution and terminal accounting, per-paper evidence matrix,
top-tier list with score breakdown, supported versus challenged findings,
corpus-relative distinctiveness findings, extension opportunities labeled as
inference, unresolved/failed/human-review sections, and full run/profile/policy/
component-skill provenance.

Each of the 15 EDGE entries appears once even when identity or analysis fails.
The table distinguishes `declared`, `extracted`, `identity_resolved`,
`analysis_complete`, `analysis_unresolved`, and `failed`; identity resolution
must not be reported as completed analysis.

Top-tier membership is boolean output of the frozen policy. Display every
criterion score, threshold failure, uncertainty flag, and cited supported claim
used in the explanation. Do not store or display `revolutionary` as a boolean.

The renderer must not add prose claims. It renders accepted reviewer findings,
canonical supported claims, deterministic scores, warnings, and failures.
