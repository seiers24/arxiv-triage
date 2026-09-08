# Research objectives

Objective profiles define what makes a paper relevant and useful for a
particular research purpose. They let the same evidence pipeline support
Micron-oriented research, personal research, or other use cases without
changing the reader or critic's universal evidence rules.

The canonical contract is in
[`docs/schema.md`](../docs/schema.md#objective-profile-contract).

## Create a profile

1. Copy an existing profile such as `personal-research.json`.
2. Give it a unique `objective_id` and save it as
   `objectives/<objective-id>.json`.
3. State one clear `research_question`.
4. Define what is included and excluded from the research scope.
5. Define a small set of relevance categories.
6. Describe what makes a follow-up experiment valuable under
   `extension_priorities`.
7. Choose ranking weights before examining the resulting rankings.
8. Check that the file is valid JSON.

```bash
uv run --no-cache python -m json.tool objectives/<objective-id>.json >/dev/null
```

This command checks JSON syntax only. The pipeline's schema validator must also
validate the profile before using it.

## Required shape

```json
{
  "schema_version": "1.0",
  "objective_id": "example-research",
  "title": "Example research objective",
  "research_question": "Which papers offer practical directions for this research program?",
  "scope": {
    "include": [
      "topics that directly address the research question"
    ],
    "exclude": [
      "papers with no relevant technical contribution"
    ]
  },
  "relevance_categories": [
    {
      "id": "core_topic",
      "description": "Directly addresses the central research topic"
    },
    {
      "id": "enabling_method",
      "description": "Provides a method or tool needed by the research program"
    }
  ],
  "ranking": {
    "relevance_weight": 10,
    "technical_importance_weight": 6,
    "extendability_weight": 4
  },
  "extension_priorities": [
    "experiments feasible with available resources",
    "work that can be reproduced using public artifacts"
  ]
}
```

## Field guidance

- `objective_id`: Use lowercase letters, digits, and internal hyphens. Keep it
  stable when refining the same profile.
- `research_question`: Describe the decision the resulting brief should help
  you make—not merely a broad subject area.
- `scope.include`: List concrete topics, methods, systems, or outcomes that
  count as relevant. At least one entry is required.
- `scope.exclude`: Identify plausible-looking work that should not receive a
  high relevance score. The list may be empty.
- `relevance_categories`: Define 1–20 distinct category IDs using lowercase
  letters, digits, and underscores. Do not define `not_relevant`; the reader
  uses a `null` category when relevance is zero.
- `extension_priorities`: State practical constraints such as available
  hardware, time horizon, desired artifacts, or acceptable experiment size.
- `ranking`: Use integers from `0` through `100`. At least one weight must be
  greater than zero.

The deterministic score is:

```text
base_score =
  relevance_weight * objective_relevance
  + technical_importance_weight * technical_importance
  + extendability_weight * int(extendable)
```

`objective_relevance` and `extendable` are interpreted using the selected
profile. `technical_importance` remains objective-independent. Critic failures
are review gates and cannot be overridden by ranking weights.

## Reproducibility

Do not add an `objective_hash` field to the profile. At run start, deterministic
code computes the hash from canonical JSON and freezes a copy under
`data/objectives/<objective-hash>.json`.

Editing a profile changes its hash even when `objective_id` stays the same.
Historical results therefore remain tied to the exact profile version used.
Scores created under different objective hashes must be evaluated separately;
their numeric values are not directly comparable.

## Evaluation

Universal golden labels—claim support, evidence type, provenance, and source
spans—can be reused across objectives. Relevance, category, extension value,
and priority labels must be created separately for each objective profile as
described in [`docs/evaluation.md`](../docs/evaluation.md).
