# Plan 3: Proposal Relevance

## Goal

Given a user-authored proposal in Markdown, use an orchestrator-only skill to
translate it into a typed proposal specification, construct and document a
high-recall literature corpus, analyze each paper, and report how the retrieved
evidence affects novelty and feasibility.

The component must never claim that a proposal is globally novel. It reports
what was or was not found within a frozen, documented search protocol.

## Dependency on Plans 1 and 2

This plan uses the core artifacts, agents, reviewer, source packets, trace,
database, and workflow state machine from Plan 1. Reuse the workshop component's
proven patterns for frozen acquisition responses, complete corpus accounting,
full-source handling, objective profiles, skills, and human-review queues.

Do not require workshop-specific schemas or terminology.

## Orchestrator skill for proposal compilation

The orchestrator loads a dedicated `proposal-to-spec` skill and translates the
source `.md` into `proposal-spec.json`. Proposal conversion is input
normalization, not paper criticism, so the critic does not participate. The
conversion is still a judgment-bearing model step and is traced with the source
Markdown hash, conversion-skill hash, model ID, raw attempt, and output hash.

The original Markdown is frozen and hashed. Every field in the specification is
either:

- `stated`: supported by an exact Markdown source span
- `normalized`: a meaning-preserving reformulation with a source span
- `inferred`: introduced for search or analysis and never attributed to the user

Deterministic validation enforces the schema, field types, provenance labels,
and exact Markdown substring rule for every claimed source span. A malformed
conversion receives one schema-focused retry. Materially unspecified fields
remain `uncertain`; they are not silently converted into proposal claims or hard
search constraints. Raw failed attempts remain append-only.

The proposal search cannot start until the validated specification exists.

## `ProposalSpec`

At minimum:

- proposal ID, title, source path, and source hash
- research question
- problem statement
- proposed mechanism
- expected outcome
- assumptions
- constraints and target environment
- proposed baselines
- success metrics
- user-stated novelty claim
- concept groups and synonyms for search, labeled `inferred`
- exclusions
- uncertain or underspecified fields
- source, conversion-skill, model, and output artifact hashes

The AI may generate synonyms and adjacent terminology, but those remain search
inferences. It may not strengthen the proposal's novelty claim or silently fill
an unspecified mechanism, environment, or success criterion.

## Proposal objective profile

Use structured, non-collapsing dimensions:

| Dimension | Question |
|---|---|
| Problem overlap | Does the paper address the same research problem? |
| Mechanism overlap | Does it use the same or an equivalent mechanism? |
| Assumption overlap | Are the operating assumptions materially comparable? |
| Outcome overlap | Does it achieve the proposed outcome or metric? |
| Novelty impact | Does it weaken a specific user-stated novelty claim? |
| Feasibility impact | Does it support or contradict feasibility assumptions? |

The permitted overall labels are:

- `directly_answers`
- `partial_overlap`
- `enabling_prior_art`
- `contradicts_assumption`
- `feasibility_warning`
- `background_only`
- `uncertain`

Every non-background label cites supported claim IDs and the exact proposal
fields affected. Novelty impact and feasibility impact are reported separately.

## Search protocol

Construct several query families from the validated proposal specification:

1. exact user terminology
2. problem synonyms
3. mechanism synonyms and equivalent techniques
4. desired outcome and metrics
5. assumption or target-environment terms
6. combinations of problem, mechanism, and outcome
7. known seed-paper references when supplied

Run explicit queries across configured providers, initially arXiv and Tavily.
Add structured citation or scholarly-index providers only behind the shared
acquisition interface.

For every query, preserve:

- provider and exact parameters
- execution time and response/request IDs
- raw response path and hash
- returned ranks and URLs
- deduplication and identity-resolution decisions
- inclusion, exclusion, and failure reasons

Tavily answers and snippets are discovery metadata, never paper evidence.

## Corpus expansion and stopping

For included papers, optionally expand through backward references and forward
citations when a supported provider is available. Record every expansion round
and its incremental yield.

The stopping rule must be declared before execution. A starting rule is:

- every planned query family has run
- known seed papers were recovered or their absence is explained
- two consecutive expansion rounds produce no new included papers
- provider and budget limits have not forced early termination

If a budget, source failure, or result cap ends the search first, coverage is
`bounded_incomplete` and the final novelty conclusion is `inconclusive`.

The program may say:

> No directly answering paper was found in the documented corpus.

It may not say:

> No prior work exists.

## Proposal-relevance component skill

Create two related skills:

```text
.claude/skills/proposal-to-spec/
  SKILL.md
  references/
    schema.md
    provenance-rules.md
    examples.md

.claude/skills/proposal-relevance/
  SKILL.md
  references/
    search-protocol.md
    reader-focus.md
    critic-rubric.md
    reviewer-rubric.md
    output-contract.md
```

### Reader overlay

In addition to core evidence, require focused extraction of:

- problem definition and target setting
- mechanism and technically equivalent operations
- assumptions and constraints
- evaluated outcomes, metrics, and baselines
- limitations that affect applicability
- explicit statements of difference from prior work
- details that support or weaken proposal feasibility

The reader does not decide whether the proposal is novel or solved.

### Critic overlay

Require the critic to:

- verify every paper claim in the per-paper job
- compare only supported paper evidence to validated proposal fields
- distinguish direct solution, partial overlap, enabling work, contradiction,
  feasibility impact, and background
- explain why assumptions and experimental settings are or are not comparable
- return `uncertain` when the source cannot support a definite impact

### Reviewer overlay

Require the reviewer to:

- verify corpus accounting and stopping conditions
- challenge any global-novelty wording
- compare direct-solution and partial-overlap judgments across the corpus
- identify conflicting critic assessments
- ensure feasibility and novelty impacts remain separate
- ensure negative search results are qualified by providers, queries, dates, and
  coverage status
- create a human-review queue for uncertain or high-impact papers

## Workflow

```text
proposal.md
  -> orchestrator loads proposal-to-spec skill
  -> validated proposal specification
  -> objective profile and frozen search plan
  -> multi-family discovery and corpus manifest
  -> source resolution and freeze for every candidate
  -> one reader per paper
  -> one critic per valid reader record
  -> bounded citation expansion, if configured
  -> final corpus and terminal accounting
  -> deterministic per-paper grouping
  -> one corpus reviewer
  -> deterministic relevance and coverage report
```

If expansion adds a paper, that paper receives the same complete reader and
critic path. No paper can be cited from a search snippet alone.

## Tests

### Proposal compilation tests

Create Markdown fixtures containing:

- an explicit mechanism and metrics
- an underspecified mechanism
- multiple conditional assumptions
- a negative constraint
- a user-stated novelty claim
- language that could be incorrectly strengthened during normalization

Verify:

- every stated/normalized field has an exact source span
- inferred synonyms are labeled inferred
- missing fields remain missing or uncertain
- a planted stronger novelty claim is rejected by the golden conversion rubric
- canonicalization and hashing are stable for identical validated output bytes
- a schema-invalid conversion receives at most one correction attempt

### Search and coverage tests

Use frozen provider responses containing:

- a known direct-solution paper under exact terminology
- an equivalent method using different terminology
- a high-ranking irrelevant result
- duplicates across arXiv and the web
- an unavailable paper
- a result found only through citation expansion

Verify known-item recovery, deduplication, failure visibility, expansion yield,
stopping behavior, and incomplete-coverage wording.

### Reader and critic tests

- direct solution with comparable assumptions
- similar mechanism for a different problem
- same problem with a materially different mechanism
- paper contradicting one feasibility assumption
- abstract overclaim corrected by full text
- uncertain applicability requiring human review
- planted unsupported novelty collision rejected

### Reviewer and report tests

- no global-novelty claim from a bounded corpus
- direct and partial overlaps remain distinct
- novelty and feasibility impacts remain separate
- conflicting per-paper assessments are surfaced
- every conclusion cites proposal fields and supported paper claims
- failures, exclusions, and unresolved papers affect coverage status
- a budget-truncated search yields `inconclusive`

### Human evaluation

For a small proposal with known related work, hand-label:

- relevant-paper inclusion
- direct versus partial overlap
- affected proposal fields
- novelty and feasibility impact
- uncertainty requiring review

Measure retrieval recall on the known set, assessment agreement, unsupported
impact statements, human-review usefulness, and reader-only versus
reader-plus-critic errors.

## Persistence and retrieval

Store canonical proposal specifications and assessments in the shared artifact
tree and SQLite index. Add FTS5 columns for:

- proposal problem and mechanism
- verified paper problem and method
- supported claims
- novelty and feasibility impact explanations

Proposal generation is not part of this plan. The validated evidence becomes
retrievable input for a later, separately evaluated proposal-generation action.

## Output

Produce:

- validated proposal specification with unresolved fields
- complete search protocol and coverage report
- all included, excluded, unresolved, and failed papers
- per-paper relevance/impact table
- direct-answer and partial-overlap sections
- novelty-impact and feasibility-impact summaries
- uncertain high-impact papers for human review
- qualified conclusion limited to the documented corpus
- full source, worker, skill, model, and profile provenance

## Implementation sequence

1. Add proposal-source and proposal-spec schemas.
2. Write the orchestrator-only `proposal-to-spec` skill and conversion fixtures.
3. Implement objective-profile generation from the validated proposal.
4. Implement multi-family arXiv and Tavily search with frozen responses.
5. Implement corpus deduplication, expansion, and coverage accounting.
6. Write reader, critic, and reviewer skill overlays.
7. Implement impact grouping and deterministic report rendering.
8. Run frozen-response integration tests.
9. Run one live proposal investigation against a hand-labeled known set.

## Definition of done

- AI translates proposal Markdown without silently changing its meaning.
- Deterministic schema and span validation runs before the translation controls search.
- All planned query families and stopping conditions are auditable.
- Every included paper receives a frozen source, reader, and critic path.
- Every impact judgment references supported paper claims and validated proposal fields.
- The reviewer blocks unqualified global-novelty conclusions.
- Search failures and incomplete coverage produce an inconclusive, not reassuring, result.
- All records remain available for later retrieval and proposal-generation work.
