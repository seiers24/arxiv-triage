# Plan 1: Core Investigation Platform

## Goal

Build the pieces shared by every literature investigation, independent of how
the paper corpus is discovered. This plan produces no workshop-specific or
proposal-specific conclusions. It establishes the evidence contracts, storage,
workflow state machine, agent roles, validation, tracing, and deterministic
report inputs on which later components depend.

The platform accepts a frozen investigation specification, objective profile,
search plan, and corpus. It produces validated per-paper evidence, per-paper
critic verdicts, one corpus-level review, and a complete accounting of every
paper and agent invocation.

## Architectural decision: add a corpus reviewer

Use one orchestrator and three worker roles, still with a one-level hierarchy:

| Role | Scope | Reads | Produces | Must not do |
|---|---|---|---|---|
| Orchestrator | One investigation | Specifications, workflow state, validated artifacts | Dispatches, state transitions, terminal accounting | Read papers, repair worker output, or make unsupported research judgments |
| Paper reader | One paper | One frozen source packet plus a bounded component focus | Objective-neutral evidence and focused observations | Fetch, rank papers, verify itself, or declare global novelty |
| Critic | One paper | Frozen paper source plus its reader record | Per-claim verdicts, objective assessment, uncertainty flags | Rewrite the reader record, compare the whole corpus, or produce the final ranking |
| Reviewer | One completed corpus | Corpus manifest, validated reader records, critic verdicts, deterministic scores | Cross-paper challenges, corpus-level findings, human-review queue, report readiness verdict | Fetch sources, silently edit records, or conceal unresolved papers |

The reviewer is justified because cross-paper distinctiveness and final-report
quality are not per-paper questions. Giving those decisions to the orchestrator
would combine workflow control, synthesis, and self-review. Reusing the critic
for a corpus-sized task would also blur its bounded per-paper contract.

The reviewer is invoked once per investigation, after every corpus member has a
terminal per-paper state. It cites only validated claim, verdict, assessment,
and corpus-membership identifiers. A deterministic renderer turns its typed
output into the final report.

Record this decision in `docs/decisions.md` when implementation begins, and
update the role table in `AGENTS.md` before adding the reviewer definition.

## Separation of responsibilities

The orchestrator requests operations, but deterministic code enforces the
workflow. Correctness must not depend on the orchestrator remembering that a
paper needs to be fetched before dispatch or that only one canonical critic
record may be accepted.

Per paper, the state machine is:

```text
discovered
  -> source_resolved
  -> source_frozen
  -> reader_dispatched
  -> reader_validated
  -> critic_dispatched
  -> complete | unresolved | failed
```

The corpus reviewer can run only after every paper is `complete`, `unresolved`,
or `failed`. The investigation can be rendered only after the reviewer returns
a valid artifact or the reviewer failure is surfaced explicitly.

One reader and one critic *result* are canonical per paper and investigation.
Retries are separate append-only agent runs and remain visible. A uniqueness
constraint and workflow transition checks prevent duplicate canonical results.

## Universal inputs

Define and validate these before worker implementation:

### `InvestigationSpec`

- `investigation_id`
- `kind`: initially `workshop` or `proposal_relevance`
- `question`
- `scope`
- `requested_outputs`
- `uncertainty_policy`
- creation timestamp and content hash

### `ObjectiveProfile`

- stable profile ID and schema version
- criterion definitions
- score anchors, gates, and weights
- permitted assessment labels
- human-review triggers
- origin: user-authored, AI-drafted, or template-derived
- content hash

### `SearchPlan`

- acquisition providers and explicit parameters
- query families or authoritative entry points
- inclusion and exclusion rules
- date and venue bounds
- stopping or completeness rule
- budget limits
- content hash

The search plan and objective profile are different artifacts. Search describes
how a corpus is constructed; the profile describes how retrieved evidence is
judged.

## Universal paper identity and source packet

Replace `arxiv_id` as the database-wide identity with an internal `paper_id`.
A paper can have zero or more identifiers:

- versioned arXiv ID
- DOI
- OpenReview forum or note ID
- proceedings URL
- canonical source URL

`SourcePacket` contains the exact material supplied to the reader:

- `paper_id`
- bibliographic metadata and identifier set
- source format and retrieval method
- original-document path and SHA-256
- normalized-text path and SHA-256
- ordered sections or paragraphs with stable locator IDs
- retrieval failures or missing sections

HTML is preferred when it preserves usable structure. PDF is the fallback.
Claims cite exact normalized source spans plus locator IDs and the document hash.

## Canonical artifact layout

Validated JSON artifacts are the evidence source of truth. SQLite is a
rebuildable query index. Raw responses and invalid attempts are append-only.

```text
data/
  investigations/<investigation-id>/
    investigation.json
    objective-profile.json
    search-plan.json
    corpus.json
    discovery/
      raw/
      attempts/
    papers/<paper-id>/
      identity.json
      sources/
        source-packet.json
        original.*
        normalized.txt
      reader/
        canonical.json
        attempts/<agent-run-id>.json
      critic/
        canonical.json
        attempts/<agent-run-id>.json
    review/
      canonical.json
      attempts/<agent-run-id>.json

logs/
  trace.jsonl

out/
  <investigation-id>/
    report.md
    papers.csv
    human-review.json
```

Every canonical artifact records the hashes of all inputs that produced it.
Artifacts from different source, profile, prompt, or schema hashes are not
silently combined.

## SQLite schema

Create a new schema rather than stretching the current arXiv-specific tables.
The initial tables are:

| Table | Purpose |
|---|---|
| `investigations` | Investigation identity, kind, hashes, timestamps, status |
| `objective_profiles` | Versioned profile artifacts and hashes |
| `search_plans` | Versioned discovery protocols and hashes |
| `papers` | Internal paper identity and normalized bibliographic metadata |
| `paper_identifiers` | arXiv, DOI, OpenReview, URL, and proceedings identifiers |
| `corpus_membership` | Paper status, discovery source, inclusion/exclusion reason |
| `source_documents` | Original/normalized paths, formats, hashes, fetch status |
| `agent_runs` | One row per dispatch attempt, including failures and retries |
| `reader_records` | Canonical validated reader artifact per investigation/paper |
| `claims` | Extracted claims and source locators |
| `critic_records` | Canonical critic artifact and reader/source hashes |
| `verdicts` | Per-claim critic dispositions |
| `objective_assessments` | Per-paper, profile-relative judgments |
| `review_records` | One corpus-level reviewer artifact per investigation |
| `review_items` | Challenges and human-review queue entries |

Use foreign keys and unique constraints to enforce:

- A reader cannot be canonical without a successfully frozen source document.
- A critic cannot be canonical without the exact canonical reader record.
- A verdict cannot reference another paper or reader run.
- At most one canonical reader, critic, and reviewer record exists for its
  declared scope and input hashes.
- Every corpus member has exactly one terminal state before review.

SQLite FTS5 over titles, abstracts, methods, and supported claims is sufficient
for initial cross-run retrieval. Do not add a vector database in this plan.

## Agent trace contract

`logs/trace.jsonl` is the canonical append-only dispatch ledger. SQLite indexes
it but does not replace it. Every attempted dispatch records:

- schema version and unique `agent_run_id`
- investigation and paper IDs, with `paper_id: null` for corpus review
- role and typed job
- model ID
- worker-definition hash
- component-skill hash or `null`
- objective-profile hash
- source/input artifact hashes
- start/end timestamps and duration
- retry count
- raw-attempt path and hash
- canonical-artifact path and hash when validation passes
- validation result and visible error
- token counts and cost when available
- compact verdict summary for critic and reviewer runs

Trace writing must tolerate a dispatch that fails before producing output. The
failed event still receives a run ID and error.

## Agent definitions

Create:

```text
.claude/agents/orchestrator.md
.claude/agents/paper-reader.md
.claude/agents/critic.md
.claude/agents/reviewer.md
```

Agent definitions contain stable role boundaries, provenance rules, retry
limits, and output discipline. Component knowledge is not copied into them.
Workshop and proposal skills supply bounded overlays at dispatch time.

All workers return exactly one JSON object. They cannot call retrieval tools or
spawn other agents. The orchestrator may dispatch workers but cannot alter their
artifacts. A component overlay can narrow attention but cannot weaken base
source, provenance, schema, isolation, or failure-visibility rules.

## Shared worker contracts

### Reader output

At minimum:

- identity and all input hashes
- problem and method
- paper-stated contributions
- claims with claim kind, exact span, locator, evidence modality, and provenance
- experimental setup, baselines, metrics, results, limitations, and assumptions
- component-focused observations, clearly separated from core evidence

### Critic output

At minimum:

- one verdict per reader claim
- source-span and evidence-modality check
- unsupported and overclaimed reasons
- objective assessment tied only to supported claim IDs
- uncertainty and human-review triggers

### Reviewer output

At minimum:

- corpus accounting check
- challenges to comparative or ranking conclusions
- corpus-level findings with evidence references
- unresolved and failed-paper treatment
- human-review queue
- `ready`, `ready_with_warnings`, or `blocked` report verdict

The reviewer cannot promote an unsupported claim or remove a failure.

## Deterministic scripts

Implement small commands over shared Python modules:

- `validate.py`: strict Pydantic validation and cross-artifact invariants
- `db.py`: rebuild/index canonical artifacts and trace events
- `fetch.py`: resolve and freeze a source document from a known paper reference
- `workflow.py`: legal transitions, dispatch eligibility, retry bounds, terminal accounting
- `rank.py`: profile-defined arithmetic and gates only
- `render.py`: Markdown/CSV generation from validated artifacts
- `trace.py`: append, validate, and summarize trace events

Fetching may call external APIs, but requests and responses are frozen. Scripts
must not accept synthesized search answers as evidence.

## Tests and gates

### Schema tests

- Reject unknown fields, missing hashes, invalid enums, and incompatible versions.
- Reject a claim whose span/locator is absent from the normalized source.
- Reject `supported` for a null or mismatched source span.
- Reject cross-paper and cross-run claim references.
- Reject objective assessments that cite unsupported claims.

### Workflow tests

- Prevent reader dispatch before source freeze.
- Prevent critic dispatch before reader validation.
- Prevent duplicate canonical reader or critic records.
- Preserve all retry attempts.
- Enforce bounded retries per job type.
- Prevent reviewer dispatch until every paper is terminal.
- Refuse successful completion while any paper is unaccounted for.

### Persistence and trace tests

- Rebuild SQLite from artifacts and trace without information loss.
- Make repeated indexing idempotent.
- Roll back partial database transactions.
- Record failures that produce no worker artifact.
- Verify all stored hashes against bytes on disk.

### Agent contract tests

- Reader does not fetch, rank, or declare novelty.
- Critic covers every claim and does not rewrite reader output.
- Reviewer cites valid records and does not hide unresolved items.
- Component instructions cannot override base evidence invariants.

## Implementation sequence

1. Record the reviewer decision and update repository-level role rules.
2. Freeze schema version `2.0` in `docs/schema.md`.
3. Implement Pydantic models and cross-artifact validators.
4. Implement the run directory and canonical artifact writer.
5. Implement trace append/validation and SQLite rebuilding.
6. Implement the state machine and dispatch eligibility checks.
7. Complete the reader, critic, reviewer, and orchestrator definitions.
8. Add deterministic fetch/source-packet creation.
9. Add ranking and rendering primitives.
10. Pass core unit and integration tests using synthetic frozen papers.

## Definition of done

- A synthetic multi-paper investigation runs from frozen corpus to rendered report.
- Exactly one canonical reader and critic result exists per paper.
- One corpus reviewer runs after all papers are terminal.
- Source-before-reader and reader-before-critic ordering is mechanically enforced.
- All claims, assessments, and review findings trace to compatible hashed inputs.
- SQLite can be deleted and rebuilt entirely from canonical artifacts and trace.
- Failed and unresolved papers remain visible in the output.
- No component-specific assumptions exist in the base worker definitions.
