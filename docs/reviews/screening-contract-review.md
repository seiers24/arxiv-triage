# Screening contract review

**Status:** proposed; human approval required before implementation

**Created:** 2026-09-13

This document proposes the smallest coherent contract for abstract screening.
It is a review artifact, not an active worker instruction or runtime contract.
Nothing in this file makes the paper-screener eligible for dispatch.

## Why this review is required

The approved paper-screener behavior assumes frozen candidates, bounded batch
tasks, exact output validation, and visible decisions. The current contracts
have none of those objects. They also support only paper-scoped reader and
critic runs and one corpus-scoped reviewer run; they cannot identify several
screening batches in one investigation.

There is also a semantic mismatch that must not be resolved implicitly:
`ObjectiveProfile` contains assessment criteria, while `SearchPlan` contains
the investigation's inclusion and exclusion rules. Supplying the objective
alone therefore does not give the screener the stated screening boundary.

## Proposed data flow

```text
InvestigationSpec + SearchPlan + ObjectiveProfile
                       |
                       v
             deterministic discovery
                       |
                       v
       normalize -> deduplicate -> resolve identity
                       |
                       v
        candidates.json + candidate_set_hash
                 (immutable barrier)
                       |
                       v
          deterministic ordered partition
             /             |             \
        batch-001       batch-002       batch-N
             |              |              |
       screener run    screener run    screener run
             |              |              |
       validate whole  validate whole  validate whole
             \              |              /
              canonical ScreeningRecords
                       |
                       v
         deterministic global coverage check
                       |
                       v
       route every frozen candidate exactly once
       selected ----------> included
       needs_review -------> included
       screened_out -------> excluded
       identity failure ---> membership_unresolved
                       |
                       v
                 CorpusManifest
```

The corpus may freeze only when discovery completion is proven and every
required screening batch has one valid canonical result. A genuine
zero-candidate result creates no screening jobs and may pass the barrier only
when the search plan's completion rule was satisfied.

## Proposed contracts

All closed objects forbid unknown fields and retain `schema_version`. Hashes
use the existing canonical JSON rules.

### `ScreeningScope`

```text
schema_version    Literal["2.0"]
question          Text
inclusion_rules   list[Text]
exclusion_rules   list[Text]
scope_hash        Sha256
```

This is the exact semantic boundary for screening. It is materialized as a
reviewable investigation input before dispatch from the investigation question
and component-owned search plan. It may be AI-drafted by an approved
orchestrator skill, but task preparation only validates and copies the frozen
object. It does not contain ranking weights or ask the screener to judge
novelty, importance, or extendability.

Proposed invariants:

- at least one inclusion rule is required;
- rules preserve order and contain no exact duplicates;
- `scope_hash` is the object's self-hash;
- the orchestrator may prepare or validate the object but may not silently
  invent missing scope rules during screening.

### `CandidatePaper`

```text
schema_version    Literal["2.0"]
paper_identity    PaperIdentity
abstract          Text | null
discovery_refs    list[Identifier]
candidate_hash    Sha256
```

`paper_identity.paper_id` is the durable internal candidate identifier; a
second `candidate_id` is unnecessary. A nullable abstract keeps a title-only
candidate visible and routes semantic uncertainty to `needs_review` rather
than dropping it before screening.

Proposed invariants:

- `paper_identity`, `discovery_refs`, and `candidate_hash` validate exactly;
- discovery references are non-empty and unique;
- the candidate hash binds the exact title, authors, identifiers, identity
  status, abstract, and provenance references;
- candidates are objective-neutral and may be reused with another objective.

### `CandidateSet`

```text
schema_version         Literal["2.0"]
investigation_id       Identifier
search_plan_hash       Sha256
discovery_ledger_hash  Sha256
frozen_at              UtcTimestamp
candidates             list[CandidatePaper]
candidate_set_hash     Sha256
```

This is the exact `candidates.json` payload. Candidate paper IDs are unique,
array order is canonical, and `candidate_set_hash` is the object's self-hash.
The set may be empty only after deterministic discovery has recorded that the
active search completion rule succeeded. A provider error or exhausted search
cannot be represented as a successful empty candidate set.

### `ScreeningEvidenceSpan`

```text
field        Literal["title", "abstract"]
start_char   NonNegativeInt
end_char     NonNegativeInt
quote        Text
```

The exact quote must reconstruct from the selected candidate field using
Python Unicode code-point offsets. An empty span list remains valid for an
absence-based exclusion or unavoidable ambiguity. Typed title spans replace
the current prompt's abstract-only span wording so title-based decisions can
also carry exact evidence.

### `ScreeningTask`

```text
schema_version          Literal["2.0"]
job_type                Literal["paper_screen"]
agent_run_id            Identifier
investigation_id        Identifier
screening_batch_id      Identifier
candidate_set_hash      Sha256
batch_ordinal           PositiveInt
objective_profile       ObjectiveProfile
screening_scope         ScreeningScope
candidates              list[CandidatePaper]
batch_size_limit        PositiveInt
output_schema_version   Literal["2.0"]
input_hash              Sha256
```

Proposed invariants:

- `1 <= len(candidates) <= batch_size_limit`;
- paper IDs and candidate hashes are unique within the ordered batch;
- candidate order is contractual;
- all embedded self-hashes validate;
- `input_hash` is the task self-hash and binds the batch identity, complete
  candidate-set identity, objective, screening scope, ordered candidates, and
  explicit bound;
- an empty corpus creates no task.

### `ScreeningDecision`

```text
paper_id          Identifier
candidate_hash    Sha256
state             Literal["selected", "screened_out", "needs_review"]
reason            Text
evidence_spans    list[ScreeningEvidenceSpan]
```

The candidate hash proves which frozen metadata the worker saw. The objective
and scope hashes belong once on the enclosing record, avoiding repetition in
every decision.

### `ScreeningRecord`

```text
schema_version          Literal["2.0"]
role                    Literal["paper_screener"]
job_type                Literal["paper_screen"]
agent_run_id            Identifier
investigation_id        Identifier
screening_batch_id      Identifier
candidate_set_hash      Sha256
objective_profile_hash  Sha256
screening_scope_hash    Sha256
input_hash              Sha256
decisions               list[ScreeningDecision]
```

The single admission gateway is:

```text
validate_screening_output(task, raw_output) -> ScreeningRecord
```

It parses exactly one JSON object, validates the closed schema, verifies every
identity and hash, reconstructs every evidence span, and requires the ordered
decision paper IDs and candidate hashes to equal the ordered task candidates.
Any missing, duplicate, foreign, substituted, or reordered candidate rejects
the entire physical attempt. Semantic agreement with the decision remains an
evaluation concern, not a deterministic validator function.

## Proposed execution identity and lifecycle

Add `paper_screener` / `paper_screen` to the role and job enums. Add nullable
`screening_batch_id` to `AgentRun` and `TraceEvent` with this exclusive scope
rule:

| Role | `paper_id` | `screening_batch_id` |
|---|---:|---:|
| paper reader or critic | required | null |
| paper screener | null | required |
| corpus reviewer | null | null |

The logical screening key is
`(investigation_id, screening_batch_id, job_type)`. Physical retries retain
the same task content and batch identity but receive a new `agent_run_id` and
incremented attempt number.

Use explicit investigation states:

```text
discovering
  -> candidates_frozen
  -> screening
  -> corpus_frozen
```

This makes it impossible to mutate the candidate population after dispatch or
to present a partially screened population as a frozen corpus.

## Proposed retry and failure policy

- One screening batch is one atomic logical job; valid decisions from an
  invalid partial response are not salvaged.
- The existing maximum of two physical attempts applies.
- Only transport failure, missing output, malformed JSON, or correctable
  contract failure permits the second attempt.
- A valid semantic state is never retried merely because it is surprising.
- Independent batches continue after another batch fails.
- If any batch exhausts its attempts, the investigation fails after the other
  in-flight batches reach terminal states. No missing decision is fabricated
  as `needs_review`, `screened_out`, or `membership_unresolved`.

## Proposed persistence

```text
data/investigations/<investigation-id>/
  discovery/candidates.json
  runs/<agent-run-id>/
    input.json
    raw-output.txt
    parsed.json
    validation.json
    outcome.json
  screening/<objective-hash>/<screening-batch-id>/canonical.json
  corpus.json
```

`candidates.json` is the authoritative ordered candidate set. The logical batch
path remains stable across physical retries; invalid attempts remain only in
their run bundles. The first slice does not change `CorpusEntry`: a routing
reason resolves to its canonical screening decision through the shared
investigation ID, objective hash, and paper ID. Identity failures have no
screening-derived membership reason even if they were semantically screened.

SQLite remains a rebuildable projection. The minimal delta is:

- `candidate_papers` keyed by investigation and paper;
- `screening_records` unique by investigation and screening batch;
- `screening_decisions` unique by investigation and paper;
- nullable `screening_batch_id` on `agent_runs`;
- separate uniqueness indexes for paper, batch, and corpus logical scopes;
- an explicit SQLite index-schema version checked during initialization.

The existing database role check cannot be altered by `CREATE TABLE IF NOT
EXISTS`. This change therefore rebuilds the caller-selected index from
canonical artifacts and trace; it does not attempt an in-place migration.

## Tools introduced by this slice

No web provider, browser, Tavily integration, or worker tool access is added.
The only new executable surfaces proposed here are deterministic Python code:

1. candidate-set freezer and hasher;
2. ordered batch partitioner;
3. screening task preparer;
4. `validate_screening_output` admission gateway;
5. investigation-wide coverage and routing guard;
6. SQLite rebuild support for the new projections.

The paper-screener continues to declare `tools: []`.

## Human decisions required

The recommendations below are intentionally not active until approved.

| ID | Recommended decision | Alternative and consequence |
|---|---|---|
| S1 | Give the worker a closed `ScreeningScope` plus the objective profile. | Objective-only input lacks inclusion/exclusion scope; passing the open `SearchPlan` exposes component-specific arbitrary JSON. |
| S2 | Use explicit `screening_batch_id` and `candidates_frozen -> screening` lifecycle stages. | Hiding screening inside discovery reduces types but cannot safely identify retries or enforce the freeze barrier. |
| S3 | Permit nullable abstracts and typed title/abstract evidence spans. | Requiring an abstract makes title-only candidates unroutable; abstract-only spans cannot evidence title-based decisions. |
| S4 | In a semantic-screening run, screen every frozen candidate; external identity failure may still override its corpus route to `membership_unresolved`. | Exempting identity failures saves screening cost but contradicts the approved statement that every candidate gets a screening state. |
| S5 | Treat each batch atomically and fail the investigation after exhausted screening attempts. | Salvaging partial output complicates canonical identity; fabricating `needs_review` hides a failed model job. |
| S6 | Do not implement processing caps or deterministic hard exclusions in this first slice; every frozen candidate receives a worker decision. | Both require additional visible dispositions or a separate deterministic-decision artifact before they can be honest. |
| S7 | `needs_review` proceeds to full analysis and remains visible, but does not immediately create a human queue item. The corpus reviewer may escalate it later. | Immediate escalation creates a second human-review lifecycle before evidence analysis. |
| S8 | A search may freeze only when its component completion rule succeeds; partial provider failure cannot masquerade as a complete or empty corpus. | A warning-only partial corpus is more available but cannot support a completeness claim. |
| S9 | Authoritative workshop membership may explicitly bypass semantic screening and include every listed paper; open discovery uses screening. The lifecycle permits `candidates_frozen -> corpus_frozen` only for this declared mode. | Screening an already closed, small workshop population risks hiding submissions and weakens the first completeness test. |
| S10 | Retain `schema_version: "2.0"`: the screening objects are new, and `screening_batch_id` is an optional nullable addition only to non-self-hashed execution metadata. Rebuild derived SQLite indexes. | Incrementing every affected contract now makes version negotiation the next phase's main complexity. Changing an existing self-hashed object under the same version remains prohibited. |

S9 is component policy, but it affects the first workshop vertical slice and is
included now so the shared workflow exposes an honest bypass rather than a
special-case shortcut later.

## Implementation order after approval

1. Amend canonical schema and decision documentation.
2. Implement the closed models and self-hash checks.
3. Implement the single screening output gateway.
4. Add run scope, lifecycle, retry, and corpus-freeze guards.
5. Add artifact and SQLite projection support.
6. Add valid, malformed, identity-mismatched, span-mismatched, partial,
   duplicate, reordered, retry, exhausted, and zero-corpus tests.
7. Update the paper-screener prompt only for the approved exact field names and
   typed evidence spans, then present that behavior diff for human review.
8. Make the paper-screener eligible only after the full network-free test suite
   passes.
