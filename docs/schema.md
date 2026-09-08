# Schema

This document defines the structured input and output contracts for the
[paper-reader agent](../.claude/agents/paper-reader.md) and the
[critic agent](../.claude/agents/critic.md).

Here, “schema” refers to the JSON artifacts exchanged between agents and
deterministic scripts—not the SQLite database schema. These contracts define
required fields, data types, allowed values, and validation rules. Version
`1.0` is intentionally limited to the frozen arXiv metadata and abstract; it
does not cover full-paper text or external retrieval. The contract is
objective-neutral: a run binds the same evidence rules to one explicit,
hash-addressed research objective that supplies the relevance categories and
ranking weights.

## General rules

- All agent outputs must be a single valid JSON object. Markdown commentary or
  JSON fences are not part of the artifact.
- Unknown fields are rejected at every object level.
- JSON `null` is accepted only where a field explicitly permits it.
- All arXiv IDs must equal the versioned `arxiv_id` in the frozen paper input.
- Evidence validity, evidence type, provenance, and claim status are universal;
  an objective profile cannot weaken or redefine them.
- Objective profiles may define relevance categories, research scope, extension
  priorities, and ranking weights. Results created under different objective
  hashes must not be compared or combined as if their scores had the same
  meaning.
- Scores are integers from `0` to `5`, inclusive. Booleans are not integers for
  validation purposes.
- Agent output is validated before it is written to a canonical artifact,
  indexed in SQLite, or passed to another agent. The unmodified response from a
  failed attempt is still preserved for audit.
- No agent may be retried more than once. In the version `1.0` runbook, only an
  invalid reader response receives one schema-correction retry; a critic is
  dispatched once per paper. Thus a reader has at most two attempts and a
  critic has at most one.
- Failed validation attempts are preserved under
  `data/attempts/{agent_run_id}/`. This directory is append-only.
- JSON artifacts use schema version `1.0`.

## Shared types

### Evidence type

Describes the evidence directly supporting one claim. If one sentence combines
claims supported by different evidence types, the reader must split it into
separate claims.

| Value | Meaning |
|---|---|
| `simulation` | Results produced by a simulator, emulator, analytical performance model, synthetic model, or trace-driven experiment rather than measurements on the claimed physical system. |
| `real_hardware` | Measurements from an implemented physical system, prototype, accelerator, memory device, server, or testbed. A claim is not real-hardware evidence merely because simulated hardware is described. |
| `theory` | A mathematical proof, derivation, bound, or analytical argument is the claim's direct support, without a reported simulation or physical measurement. |
| `none_stated` | The supplied abstract states the claim but does not identify simulation, real-hardware, or theoretical evidence for it. This is also required for a paper-stated claim with no described evaluation. |

### Provenance

Describes where a statement originated. Peer-review provenance records
publication history; it does not prove that the claim is correct.

| Value | Meaning |
|---|---|
| `preprint` | The claim is stated in the supplied arXiv preprint and the frozen metadata does not establish peer-reviewed publication. This is the default for paper-stated claims. |
| `peer_reviewed` | The claim is stated in the supplied arXiv source and the frozen `journal_reference` unambiguously identifies publication in a refereed journal or conference. A DOI or the reader's background knowledge alone is insufficient. |
| `blog_or_docs` | The claim comes from supplied external documentation rather than the paper. Version `1.0` reader inputs contain no such sources, so readers must not emit this value; supporting external sources would require a later schema version. |
| `inferred` | The workflow inferred the statement rather than the paper stating it. It is used for relevance assumptions, extension proposals, and any claim-like statement for which the reader cannot supply an exact abstract span. It must never be cited as a paper statement. |

### Claim status

Describes the verification state of a claim. `unresolved` is applied by the
workflow after bounded review; it is not a critic verdict.

| Value | Meaning |
|---|---|
| `unverified` | The claim was emitted by the reader and has not yet been reviewed by the critic. |
| `supported` | The source span exists in the frozen abstract, supports the claim without a material change in scope or certainty, and agrees with the recorded evidence type and provenance. |
| `unsupported` | The supplied source is absent or does not provide evidence for the claim, including every claim whose `source_span` is `null`. |
| `overclaimed` | The source is related to the claim, but the claim materially strengthens, broadens, generalizes, or mischaracterizes it—for example, calling a simulation result a real-hardware measurement. |
| `unresolved` | A critic returned `unsupported` or `overclaimed`, the single permitted source-bound reader re-read was completed, and the bounded workflow ended without another critic pass. The objection remains visible in the brief. |

## Objective-profile contract

An objective profile defines what makes a paper useful for one research
purpose. It never changes what counts as source support. Editable profiles live
at `objectives/<objective-id>.json`; Micron-oriented research is one profile,
not an assumption built into this schema.

| Field | Type | Required | Constraints | Description |
|---|---|---:|---|---|
| `schema_version` | string | yes | exactly `1.0` | Version of the objective-profile contract. |
| `objective_id` | string | yes | lowercase letters, digits, and internal hyphens; unique in the active profile set | Stable human-readable profile identifier. |
| `title` | string | yes | 1–200 characters | Display name for the research objective. |
| `research_question` | string | yes | 1–1,000 characters | Question the ranking is intended to help answer. |
| `scope` | object | yes | fields below | Explicit inclusion and exclusion guidance. |
| `relevance_categories` | array of objects | yes | 1–20 unique category IDs | Categories available for objective-relevance judgments. |
| `ranking` | object | yes | fields below | Deterministic weights used only after validation and criticism. |
| `extension_priorities` | array of strings | yes | 0–20 items, each 1–400 characters | Criteria for judging whether a follow-up project is useful for this objective. |

`scope` contains `include` and `exclude`, both arrays of unique strings. The
`include` array must contain at least one item; `exclude` may be empty. Each
item is 1–400 characters.

Each `relevance_categories` object contains an `id` and `description`. The `id`
uses lowercase letters, digits, and internal underscores, is unique within the
profile, and is not `not_relevant`. The description is 1–400 characters. A
reader uses `null`, rather than a profile category, when objective relevance is
zero.

`ranking` contains three non-negative integer fields:

| Field | Meaning |
|---|---|
| `relevance_weight` | Integer from `0` through `100`; multiplier for `objective_relevance`. |
| `technical_importance_weight` | Integer from `0` through `100`; multiplier for `technical_importance`. |
| `extendability_weight` | Integer from `0` through `100`; additive amount when `extendable` is `true`. |

At least one ranking weight must be greater than zero. Ranking is deterministic:

```text
base_score =
  relevance_weight * objective_relevance
  + technical_importance_weight * technical_importance
  + extendability_weight * int(extendable)
```

Critic failures remain gates applied after this calculation; a profile cannot
turn an unsupported claim into a numeric penalty instead of visible review.

For `objective_hash`, serialize the entire objective profile as compact JSON
with keys sorted lexicographically, arrays kept in source order, non-ASCII
characters written directly, and no trailing newline. Encode it as UTF-8 and
hash it with SHA-256. The profile does not store its own hash.

At run start, copy the selected canonical profile to
`data/objectives/<objective-hash>.json` before dispatching an agent. That frozen
snapshot is the source supplied to the reader and critic. An editable profile
may retain its `objective_id` as it evolves, but every changed version receives
a different hash; historical runs continue to resolve to their frozen copy.

## Paper-reader contract

### Frozen paper input

The fetcher creates one frozen paper record. Nullable metadata fields are
required so that canonical hashing does not depend on whether a producer omits
an unavailable value.

| Field | Type | Required | Constraints | Description |
|---|---|---:|---|---|
| `schema_version` | string | yes | exactly `1.0` | Version of this artifact contract. |
| `arxiv_id` | string | yes | canonical versioned arXiv ID | Exact paper ID, including a `vN` suffix. Modern IDs match `YYYY.NNNN[N]vN`; legacy IDs retain their archive prefix. |
| `title` | string | yes | 1–1,000 characters | Exact paper title supplied by the fetcher. |
| `abstract` | string | yes | 1–20,000 characters | Exact abstract inspected by the reader. |
| `authors` | array of strings | yes | at least one non-empty item | Authors in source order. |
| `published` | string | yes | RFC 3339 timestamp | Original arXiv publication time. |
| `updated` | string or null | yes | RFC 3339 timestamp when non-null | Most recent arXiv revision time; `null` when unavailable. |
| `journal_reference` | string or null | yes | non-empty when non-null | Frozen arXiv journal-reference metadata; it is not populated from reader knowledge. |
| `doi` | string or null | yes | non-empty when non-null | Frozen DOI metadata; presence alone does not establish peer review. |
| `input_hash` | string | yes | 64 lowercase hexadecimal characters | SHA-256 digest of the canonical frozen input, excluding this field. |

For `input_hash`, serialize the other fields as compact JSON with object keys
sorted lexicographically, arrays kept in source order, non-ASCII characters
written directly rather than escaped, and no trailing newline. Encode that
serialization as UTF-8 and hash the bytes with SHA-256. In Python, these JSON
settings are `sort_keys=True`, `separators=(",", ":")`, and
`ensure_ascii=False`.

Illustrative example (the title and ID are intentionally synthetic):

```json
{
  "schema_version": "1.0",
  "arxiv_id": "2601.01234v1",
  "title": "Illustrative Memory System Study",
  "abstract": "We evaluate the design in a trace-driven simulator and report lower memory traffic than the baseline.",
  "authors": ["Example Author"],
  "published": "2026-01-05T12:00:00Z",
  "updated": null,
  "journal_reference": null,
  "doi": null,
  "input_hash": "d23fd0b8f798cc6cff26facd9ff85d30df4675216e531e5114879ebb2d14cff6"
}
```

### Reader dispatch input

The reader must not fetch additional information or modify the supplied paper
or objective. Its input is one JSON object containing:

| Field | Type | Required | Constraints | Description |
|---|---|---:|---|---|
| `schema_version` | string | yes | exactly `1.0` | Version of this dispatch contract. |
| `paper` | object | yes | valid frozen paper input | Exact paper source to inspect. |
| `objective` | object | yes | valid frozen objective profile | Research purpose used for relevance and extendability judgments. |
| `objective_hash` | string | yes | 64 lowercase hexadecimal characters; matches `objective` | Identity of the exact objective profile supplied. |

The paper `input_hash` and `objective_hash` identify independent inputs. The
paper hash must remain stable when the same paper is evaluated under a
different objective.

### Reader output

| Field | Type | Required | Constraints | Description |
|---|---|---:|---|---|
| `schema_version` | string | yes | exactly `1.0` | Version of this artifact contract. |
| `role` | string | yes | exactly `reader` | Identifies the producing role. |
| `arxiv_id` | string | yes | matches input exactly | Paper being analyzed. |
| `input_hash` | string | yes | matches input exactly | Frozen input used by the reader. |
| `objective_id` | string | yes | matches `objective.objective_id` | Research objective used for judgment. |
| `objective_hash` | string | yes | matches dispatch input exactly | Exact objective-profile bytes used by the reader. |
| `problem` | string | yes | 1–600 characters | Concise problem addressed by the paper. |
| `method` | string | yes | 1–600 characters | Concise approach taken by the paper. |
| `technical_importance` | integer | yes | `0`–`5` | Estimated technical importance independent of the selected objective. |
| `objective_relevance` | integer | yes | `0`–`5` | Relevance to the selected objective profile. |
| `extendable` | boolean | yes | — | Whether the reader can identify a concrete, testable extension aligned with the objective's extension priorities. |
| `reason` | string | yes | 1–600 characters | Concise explanation of technical importance, objective relevance, and extendability. |
| `relevance_category` | string or null | yes | profile-defined category ID, or `null` | Best primary connection to the selected objective; secondary connections belong in assumptions. |
| `relevance_claim_indices` | array of integers | yes | unique, in-bounds indices | Paper claims on which the objective-relevance judgment depends. |
| `relevance_assumptions` | array of strings | yes | each item 1–400 characters | Explicit workflow inferences needed to connect the linked claims to the selected objective; empty when none are needed. |
| `claims` | array | yes | 1–20 items | Extracted technical claims, keeping paper-stated claims in source order and explicitly labeling any inference. |
| `extension_proposal` | object or null | yes | cross-field rules below | Optional analyst-inferred extension. |

Each object in `claims` contains:

| Field | Type | Required | Constraints | Description |
|---|---|---:|---|---|
| `text` | string | yes | 1–1,000 characters | Reader's concise formulation of the claim. |
| `source_span` | string or null | yes | non-empty exact abstract substring after normalization | Text supporting the claim. |
| `evidence_type` | string | yes | shared evidence enum | Evidence used by the paper for this claim. |
| `provenance` | string | yes | `preprint`, `peer_reviewed`, or `inferred` | Origin of the claim; `blog_or_docs` is unavailable in version `1.0`. |
| `status` | string | yes | exactly `unverified` | Verification state before criticism. |

A non-null `extension_proposal` contains:

| Field | Type | Required | Constraints | Description |
|---|---|---:|---|---|
| `provenance` | string | yes | exactly `inferred` | Makes clear that this is analyst judgment, not a paper claim. |
| `hypothesis` | string | yes | 1–600 characters | Testable extension hypothesis. |
| `smallest_useful_experiment` | string | yes | 1–1,000 characters | Smallest experiment that could provide useful evidence. |
| `comparison_baseline` | string | yes | 1–600 characters | Existing method or configuration against which to compare. |
| `success_metric` | string | yes | 1–600 characters | Observable criterion for success. |

Illustrative reader output:

```json
{
  "schema_version": "1.0",
  "role": "reader",
  "arxiv_id": "2601.01234v1",
  "input_hash": "d23fd0b8f798cc6cff26facd9ff85d30df4675216e531e5114879ebb2d14cff6",
  "objective_id": "personal-systems-research",
  "objective_hash": "8820e6d4a0cb3678aa1653a8e6fb3cb450e53ce3c7d19619a1d1e48aab5a0c4a",
  "problem": "Memory traffic limits the target workload.",
  "method": "The paper evaluates a traffic-reduction technique in a trace-driven simulator.",
  "technical_importance": 3,
  "objective_relevance": 4,
  "extendable": true,
  "reason": "The technique has moderate technical importance, directly addresses the objective's memory-systems scope, and has a feasible hardware follow-up.",
  "relevance_category": "memory_systems",
  "relevance_claim_indices": [0],
  "relevance_assumptions": [
    "Lower modeled traffic would reduce pressure on a comparable deployed memory hierarchy."
  ],
  "claims": [
    {
      "text": "The design lowers memory traffic relative to the baseline in a trace-driven simulation.",
      "source_span": "We evaluate the design in a trace-driven simulator and report lower memory traffic than the baseline.",
      "evidence_type": "simulation",
      "provenance": "preprint",
      "status": "unverified"
    }
  ],
  "extension_proposal": {
    "provenance": "inferred",
    "hypothesis": "The traffic reduction persists on a physical memory-system prototype.",
    "smallest_useful_experiment": "Implement the technique on one available hardware testbed and replay the evaluation workload.",
    "comparison_baseline": "The unmodified baseline configuration on the same testbed.",
    "success_metric": "A reproducible reduction in measured memory traffic without lower workload throughput."
  }
}
```

### Reader validation rules

- `arxiv_id` and `input_hash` must exactly match the supplied paper.
- `objective_id` and `objective_hash` must exactly match the supplied objective,
  and the objective hash must pass canonical validation.
- For span matching only, normalize both the abstract and `source_span` by
  replacing each maximal run of Unicode whitespace with one ASCII space and
  trimming leading and trailing whitespace. Do not change case, punctuation,
  spelling, Unicode normalization form, or word order. The normalized span
  must be a non-empty contiguous substring of the normalized abstract.
- A claim with `source_span: null` must use `provenance: inferred` and
  `evidence_type: none_stated`; it must not be phrased as though the paper
  stated it. A non-null span requires `preprint` or `peer_reviewed` provenance.
  Prefer placing objective-specific inferences in `relevance_assumptions` and
  proposed work in `extension_proposal` rather than creating an inferred claim.
- `objective_relevance` and `technical_importance` must be integers from `0`
  through `5`. The former is profile-dependent; the latter must not be raised
  or lowered merely because the paper fits the selected objective.
- Claim indices are zero-based. `relevance_claim_indices` must contain no
  duplicates, every index must address an item in `claims`, and no linked claim
  may have `inferred` provenance.
- If `objective_relevance` is `0`, `relevance_category` must be `null` and
  `relevance_claim_indices` must be empty. If `objective_relevance` is greater
  than `0`, the category must equal an ID declared in the selected objective
  and at least one paper-stated claim must be linked.
- Every relevance assumption is treated as `inferred`; it must not be phrased
  as though the paper stated or proved it.
- `extendable: true` requires a non-null `extension_proposal`. When the
  selected objective lists extension priorities, the proposal must address at
  least one of them.
  `extendable: false` requires `extension_proposal: null`.
- The extension proposal must describe a testable hypothesis, an actual
  experiment, a named comparison baseline, and an observable success metric.
- `preprint` is the default claim provenance. `peer_reviewed` is valid only
  when the frozen `journal_reference` meets the definition above.

## Critic contract

### Critic input

The critic receives the same frozen paper source, selected objective profile,
and one validated reader artifact. It does not receive the reader's hidden
reasoning, preliminary rank, other critics' opinions, or a desired conclusion.

| Field | Type | Required | Constraints | Description |
|---|---|---:|---|---|
| `schema_version` | string | yes | exactly `1.0` | Version of this artifact contract. |
| `paper` | object | yes | valid frozen paper input | Frozen paper source. |
| `objective` | object | yes | valid frozen objective profile | Profile against which relevance and extendability were judged. |
| `objective_hash` | string | yes | matches the reader and objective | Exact objective profile used for the reader dispatch. |
| `reader_record` | object | yes | valid reader output | Claims and relevance chain being evaluated. |
| `reader_run_id` | string | yes | non-empty existing reader run ID | Identifies the exact reader attempt. |

### Critic output

| Field | Type | Required | Constraints | Description |
|---|---|---:|---|---|
| `schema_version` | string | yes | exactly `1.0` | Version of this artifact contract. |
| `role` | string | yes | exactly `critic` | Identifies the producing role. |
| `arxiv_id` | string | yes | matches reader and paper | Paper being evaluated. |
| `objective_id` | string | yes | matches reader and objective | Research objective being evaluated. |
| `objective_hash` | string | yes | matches input exactly | Exact objective profile used for the judgment. |
| `reader_run_id` | string | yes | matches input exactly | Reader attempt being evaluated. |
| `verdicts` | array | yes | exactly one per reader claim | Per-claim judgments. |
| `objective_relevance_assessment` | object | yes | fields below | Verdict on the reader's objective-relevance chain. |

Each object in `verdicts` contains:

| Field | Type | Required | Constraints | Description |
|---|---|---:|---|---|
| `claim_index` | integer | yes | valid unique zero-based index | Reader claim being evaluated. |
| `status` | string | yes | `supported`, `unsupported`, or `overclaimed` | Critic verdict. |
| `reason` | string | yes | 1–600 characters | Source-based explanation of the verdict. |

`objective_relevance_assessment` contains:

| Field | Type | Required | Constraints | Description |
|---|---|---:|---|---|
| `justified` | boolean | yes | — | Whether the score, category, claim links, and stated assumptions form a defensible relevance chain. |
| `reason` | string | yes | 1–600 characters | Concise explanation tied to the linked claims and explicit assumptions. |

Illustrative critic output:

```json
{
  "schema_version": "1.0",
  "role": "critic",
  "arxiv_id": "2601.01234v1",
  "objective_id": "personal-systems-research",
  "objective_hash": "8820e6d4a0cb3678aa1653a8e6fb3cb450e53ce3c7d19619a1d1e48aab5a0c4a",
  "reader_run_id": "reader-2601.01234v1-01",
  "verdicts": [
    {
      "claim_index": 0,
      "status": "supported",
      "reason": "The normalized source span states both the simulation setting and the reported reduction relative to the baseline."
    }
  ],
  "objective_relevance_assessment": {
    "justified": true,
    "reason": "The linked claim concerns memory traffic, and the reader explicitly labels the hardware implication as an assumption."
  }
}
```

### Critic validation rules

- `arxiv_id` must match the reader record and frozen paper.
- `objective_id` and `objective_hash` must match the objective and reader
  record, and the objective hash must pass canonical validation.
- `reader_run_id` must identify the supplied reader record.
- The paper, reader input, and critic output must all have compatible schema
  version `1.0`; the paper and reader `input_hash` values must match, as must
  the objective and reader `objective_hash` values.
- Every reader claim must receive exactly one verdict. Claim indices must be
  unique, zero-based, and collectively equal `0..len(claims)-1`.
- A claim with `source_span: null` cannot receive `supported`.
- A verdict can be `supported` only if the source span passes the reader's exact
  normalized-substring rule and semantically supports the claim.
- Evidence described as simulation cannot be presented as real-hardware
  measurement. That mismatch requires `overclaimed`.
- `objective_relevance_assessment.justified` must be `false` if a claim linked by
  `relevance_claim_indices` is `unsupported` or `overclaimed`, or if an
  unstated inference is necessary to reach the assigned relevance category.
- A score can be ambitious without being invalid, but the critic must reject an
  objective-relevance chain whose score, category, assumptions, or reason
  materially exceeds the linked evidence or the selected objective.
- The critic cannot add claims, edit scores, rewrite the reader artifact, or
  assign an overall rank.

## Workflow state

Every fetched paper must eventually have exactly one terminal state:

| State | Meaning |
|---|---|
| `complete` | Reader and critic artifacts passed validation, all claims were `supported`, and the objective-relevance chain was justified. |
| `unresolved` | A valid critic returned `unsupported` or `overclaimed`, or rejected the objective-relevance chain; the single permitted source-bound re-read was recorded and the bounded review then ended. |
| `failed` | The paper could not complete because of a visible fetch, dispatch, parsing, validation, or persistence error. This includes a reader that remains invalid after its one permitted correction attempt and any invalid critic response. |

A run selects exactly one objective hash. It cannot be reported as successful
while any fetched paper lacks a terminal state under that objective. A paper
must never disappear from the final report because processing failed.

## Execution trace contract

`logs/trace.jsonl` is the append-only execution ledger. It contains one JSON
object per reader or critic dispatch, including failed attempts. Each line has:

| Field | Type | Required | Constraints | Description |
|---|---|---:|---|---|
| `schema_version` | string | yes | exactly `1.0` | Trace-event contract version. |
| `agent_run_id` | string | yes | non-empty and unique | Identifier for this exact attempt. |
| `arxiv_id` | string | yes | exact versioned paper ID | Paper handled by the dispatch. |
| `role` | string | yes | `reader` or `critic` | Dispatched worker role. |
| `timestamp` | string | yes | RFC 3339 UTC timestamp | Time at which the dispatch began. |
| `model` | string | yes | non-empty | Exact model identifier requested for the call. |
| `agent_hash` | string | yes | 64 lowercase hexadecimal characters | SHA-256 of the worker definition used for the dispatch. |
| `input_hash` | string | yes | 64 lowercase hexadecimal characters | Hash of the frozen paper input. |
| `objective_id` | string | yes | matches the selected objective | Human-readable objective identifier. |
| `objective_hash` | string | yes | 64 lowercase hexadecimal characters | Hash of the exact objective profile used for the dispatch. |
| `artifact_path` | string or null | yes | repository-relative when non-null | Location of the unmodified response; `null` only if no response artifact was produced. |
| `artifact_hash` | string or null | yes | 64 lowercase hexadecimal characters when non-null | SHA-256 of the response artifact bytes. |
| `validation_pass` | boolean | yes | — | Whether this exact response passed deterministic validation. |
| `retry_count` | integer | yes | `0` or `1` | Number of earlier attempts for the same role and paper. |
| `verdict_summary` | object or null | yes | critic events only | Counts of `supported`, `unsupported`, and `overclaimed` verdicts plus `objective_relevance_justified`; `null` for reader events or an invalid critic response. |
| `tokens_in` | integer or null | yes | non-negative when known | Input tokens reported by the model provider. |
| `tokens_out` | integer or null | yes | non-negative when known | Output tokens reported by the model provider. |
| `cost_usd` | number or null | yes | non-negative when known | Provider-reported or deterministically calculated call cost in US dollars. |
| `error` | string or null | yes | non-empty when non-null | Visible dispatch, parsing, validation, or persistence error. |

`verdict_summary` contains exactly these fields: `supported`, `unsupported`,
and `overclaimed` as non-negative integers, and
`objective_relevance_justified` as a boolean. Its three counts must sum to the
length of the critic's `verdicts`.

If `artifact_path` is `null`, `artifact_hash` must also be `null`,
`validation_pass` must be `false`, and `error` must be non-null. If
`validation_pass` is `true`, both artifact fields must be non-null and `error`
must be `null`. Unknown token or cost values remain `null`; they are never
recorded as zero unless the provider actually reported zero.

## Artifact locations

| Artifact | Location |
|---|---|
| Editable objective profiles | `objectives/<objective-id>.json` |
| Frozen objective snapshots | `data/objectives/<objective-hash>.json` |
| Fetched papers | `data/papers.json` |
| Invalid raw attempts | `data/attempts/{agent_run_id}/` |
| Reader records | `data/records/<objective-hash>/<arxiv-id>/<agent-run-id>.json` |
| Critic records | `data/verdicts/<objective-hash>/<arxiv-id>/<agent-run-id>.json` |
| Execution trace | `logs/trace.jsonl` |
| Ranked brief | `out/brief.md` |
| SQLite index | `data/triage.db` |

Objective-hash and agent-run directories prevent profile revisions and retries
from overwriting one another. Each run resolves its editable profile to the
frozen snapshot named by `objective_hash`; the editable file is not sufficient
to reconstruct a historical run. Canonical reader and critic paths use a
filesystem-safe form of the exact versioned arXiv ID: replace `/` in legacy IDs
with `__`; do not otherwise remove the version suffix or alter the ID stored
inside the JSON.

## Database mapping

Validated JSON artifacts are the evidence source of truth. SQLite is a
rebuildable query index. The table below is the target mapping;
`scripts/db.py` must be migrated to it before objective-aware version `1.0`
artifacts are ingested. Fields absent from this mapping remain in the JSON
artifact rather than causing a database redesign in version `1.0`.

| Artifact field | SQLite table | SQLite column |
|---|---|---|
| objective `objective_id` | `objectives` | `objective_id` |
| computed `objective_hash` | `objectives` | `objective_hash` |
| objective `title` | `objectives` | `title` |
| `arxiv_id` | `papers` | `arxiv_id` |
| `title` | `papers` | `title` |
| `abstract` | `papers` | `abstract` |
| `published` | `papers` | `published` |
| `input_hash` | `papers` | `input_hash` |
| agent output `arxiv_id` | `runs` | `arxiv_id` |
| agent output `objective_id` | `runs` | `objective_id` |
| agent output `objective_hash` | `runs` | `objective_hash` |
| reader `claims[].text` | `claims` | `text` |
| reader `claims[].source_span` | `claims` | `source_span` |
| reader `claims[].evidence_type` | `claims` | `evidence_type` |
| reader `claims[].provenance` | `claims` | `provenance` |
| reader `objective_relevance` | `scores` | `objective_relevance` |
| reader `technical_importance` | `scores` | `technical_importance` |
| reader `reason` | `scores` | `reason` |
| reader `extendable` | `scores` | `extendable` |
| critic `verdicts[].status` | `verdicts` | `status` |
| critic `verdicts[].reason` | `verdicts` | `reason` |

`objectives.objective_hash` identifies a frozen profile revision; an
`objective_id` may therefore appear with multiple hashes over time. The
objective's full scope, categories, ranking policy, and extension priorities
remain in the profile artifact; SQLite stores its identity and hash.
`schema_version`, objective-relevance details, extension proposals, and
workflow terminal state remain artifact or report fields in version `1.0`;
they are not silently discarded from the canonical JSON.

## Versioning

When this contract changes:

1. Update this document first.
2. Update `scripts/validate.py`.
3. Update both agent definitions.
4. Update `scripts/db.py` if storage changes.
5. Update deterministic tests and fixtures.
6. Increment `schema_version` for any incompatible contract change.
7. Do not silently compare or combine results created with incompatible schema
   versions.
