# Schema

This document defines the structured input and output contracts for the
[paper-reader agent](../.claude/agents/paper-reader.md) and the
[critic agent](../.claude/agents/critic.md).

Here, “schema” refers to the JSON artifacts exchanged between agents and
deterministic scripts—not the SQLite database schema. These contracts define
required fields, data types, allowed values, and validation rules. Version
`1.0` is intentionally limited to the frozen arXiv metadata and abstract; it
does not cover full-paper text or external retrieval.

## General rules

- All agent outputs must be a single valid JSON object. Markdown commentary or
  JSON fences are not part of the artifact.
- Unknown fields are rejected at every object level.
- JSON `null` is accepted only where a field explicitly permits it.
- All arXiv IDs must equal the versioned `arxiv_id` in the frozen paper input.
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

### Strategic-lens category

The reader selects the single best primary category. Secondary connections can
be described as assumptions but do not create additional categories.

| Value | Meaning |
|---|---|
| `dram` | DRAM devices or systems other than work specifically categorized as HBM. |
| `nand` | NAND flash devices, media, or management. |
| `hbm` | High-bandwidth memory. |
| `ssd` | Solid-state drives and their controllers or system behavior. |
| `memory_hierarchy` | Placement, caching, movement, or management across memory or storage tiers. |
| `cxl` | Compute Express Link protocols, devices, or systems. |
| `disaggregated_memory` | Pooled, remote, composable, or otherwise disaggregated memory. |
| `packaging_or_chiplets` | Advanced packaging, 2.5D/3D integration, or chiplet designs relevant to memory systems. |
| `interconnect` | On-package, board-level, rack-scale, or datacenter interconnect relevant to memory traffic. |
| `processing_or_near_memory` | Processing-in-memory or near-memory computing. |
| `memory_system_limits` | Bandwidth, capacity, latency, energy, thermal, endurance, or reliability limits in memory systems. |
| `ai_memory_demand` | Training or inference behavior that materially changes memory-system demand. |
| `not_relevant` | No defensible connection to the public datacenter-memory and AI-infrastructure lens. |

## Paper-reader contract

### Reader input

The reader receives one frozen paper record. It must not fetch additional
information or modify the supplied source. Nullable metadata fields are
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

### Reader output

| Field | Type | Required | Constraints | Description |
|---|---|---:|---|---|
| `schema_version` | string | yes | exactly `1.0` | Version of this artifact contract. |
| `role` | string | yes | exactly `reader` | Identifies the producing role. |
| `arxiv_id` | string | yes | matches input exactly | Paper being analyzed. |
| `input_hash` | string | yes | matches input exactly | Frozen input used by the reader. |
| `problem` | string | yes | 1–600 characters | Concise problem addressed by the paper. |
| `method` | string | yes | 1–600 characters | Concise approach taken by the paper. |
| `relevance` | integer | yes | `0`–`5` | Relevance to the public strategic lens. |
| `importance` | integer | yes | `0`–`5` | Estimated technical importance, independent of strategic relevance. |
| `extendable` | boolean | yes | — | Whether the reader can identify a concrete, testable extension. |
| `reason` | string | yes | 1–600 characters | Concise explanation of both scores. |
| `relevance_category` | string | yes | shared strategic-lens enum | Primary public strategic-lens connection. |
| `relevance_claim_indices` | array of integers | yes | unique, in-bounds indices | Paper claims on which the relevance judgment depends. |
| `relevance_assumptions` | array of strings | yes | each item 1–400 characters | Explicit workflow inferences needed to connect the linked claims to the strategic lens; empty when none are needed. |
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
  "problem": "Memory traffic limits the target workload.",
  "method": "The paper evaluates a traffic-reduction technique in a trace-driven simulator.",
  "relevance": 4,
  "importance": 3,
  "extendable": true,
  "reason": "The method directly concerns memory demand, but the abstract reports simulation evidence only.",
  "relevance_category": "ai_memory_demand",
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
- For span matching only, normalize both the abstract and `source_span` by
  replacing each maximal run of Unicode whitespace with one ASCII space and
  trimming leading and trailing whitespace. Do not change case, punctuation,
  spelling, Unicode normalization form, or word order. The normalized span
  must be a non-empty contiguous substring of the normalized abstract.
- A claim with `source_span: null` must use `provenance: inferred` and
  `evidence_type: none_stated`; it must not be phrased as though the paper
  stated it. A non-null span requires `preprint` or `peer_reviewed` provenance.
  Prefer placing strategic inferences in `relevance_assumptions` and proposed
  work in `extension_proposal` rather than creating an inferred claim.
- `relevance` and `importance` must be integers from `0` through `5`.
- Claim indices are zero-based. `relevance_claim_indices` must contain no
  duplicates, every index must address an item in `claims`, and no linked claim
  may have `inferred` provenance.
- If `relevance` is `0`, `relevance_category` must be `not_relevant` and
  `relevance_claim_indices` must be empty. If `relevance` is greater than `0`,
  the category must not be `not_relevant` and at least one claim must be linked.
- Every relevance assumption is treated as `inferred`; it must not be phrased
  as though the paper stated or proved it.
- `extendable: true` requires a non-null `extension_proposal`.
  `extendable: false` requires `extension_proposal: null`.
- The extension proposal must describe a testable hypothesis, an actual
  experiment, a named comparison baseline, and an observable success metric.
- `preprint` is the default claim provenance. `peer_reviewed` is valid only
  when the frozen `journal_reference` meets the definition above.

## Critic contract

### Critic input

The critic receives the same frozen paper source and one validated reader
artifact. It does not receive the reader's hidden reasoning, preliminary rank,
other critics' opinions, or a desired conclusion.

| Field | Type | Required | Constraints | Description |
|---|---|---:|---|---|
| `schema_version` | string | yes | exactly `1.0` | Version of this artifact contract. |
| `paper` | object | yes | valid reader input | Frozen paper source. |
| `reader_record` | object | yes | valid reader output | Claims and relevance chain being evaluated. |
| `reader_run_id` | string | yes | non-empty existing reader run ID | Identifies the exact reader attempt. |

### Critic output

| Field | Type | Required | Constraints | Description |
|---|---|---:|---|---|
| `schema_version` | string | yes | exactly `1.0` | Version of this artifact contract. |
| `role` | string | yes | exactly `critic` | Identifies the producing role. |
| `arxiv_id` | string | yes | matches reader and paper | Paper being evaluated. |
| `reader_run_id` | string | yes | matches input exactly | Reader attempt being evaluated. |
| `verdicts` | array | yes | exactly one per reader claim | Per-claim judgments. |
| `relevance_assessment` | object | yes | fields below | Verdict on the reader's strategic-relevance chain. |

Each object in `verdicts` contains:

| Field | Type | Required | Constraints | Description |
|---|---|---:|---|---|
| `claim_index` | integer | yes | valid unique zero-based index | Reader claim being evaluated. |
| `status` | string | yes | `supported`, `unsupported`, or `overclaimed` | Critic verdict. |
| `reason` | string | yes | 1–600 characters | Source-based explanation of the verdict. |

`relevance_assessment` contains:

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
  "reader_run_id": "reader-2601.01234v1-01",
  "verdicts": [
    {
      "claim_index": 0,
      "status": "supported",
      "reason": "The normalized source span states both the simulation setting and the reported reduction relative to the baseline."
    }
  ],
  "relevance_assessment": {
    "justified": true,
    "reason": "The linked claim concerns memory traffic, and the reader explicitly labels the hardware implication as an assumption."
  }
}
```

### Critic validation rules

- `arxiv_id` must match the reader record and frozen paper.
- `reader_run_id` must identify the supplied reader record.
- The paper, reader input, and critic output must all have compatible schema
  version `1.0`; the paper and reader `input_hash` values must match.
- Every reader claim must receive exactly one verdict. Claim indices must be
  unique, zero-based, and collectively equal `0..len(claims)-1`.
- A claim with `source_span: null` cannot receive `supported`.
- A verdict can be `supported` only if the source span passes the reader's exact
  normalized-substring rule and semantically supports the claim.
- Evidence described as simulation cannot be presented as real-hardware
  measurement. That mismatch requires `overclaimed`.
- `relevance_assessment.justified` must be `false` if a claim linked by
  `relevance_claim_indices` is `unsupported` or `overclaimed`, or if an
  unstated inference is necessary to reach the assigned relevance category.
- A score can be ambitious without being invalid, but the critic must reject a
  relevance chain whose score or reason materially exceeds the linked evidence.
- The critic cannot add claims, edit scores, rewrite the reader artifact, or
  assign an overall rank.

## Workflow state

Every fetched paper must eventually have exactly one terminal state:

| State | Meaning |
|---|---|
| `complete` | Reader and critic artifacts passed validation, all claims were `supported`, and the relevance chain was justified. |
| `unresolved` | A valid critic returned `unsupported` or `overclaimed`, or rejected the relevance chain; the single permitted source-bound re-read was recorded and the bounded review then ended. |
| `failed` | The paper could not complete because of a visible fetch, dispatch, parsing, validation, or persistence error. This includes a reader that remains invalid after its one permitted correction attempt and any invalid critic response. |

A run cannot be reported as successful while any fetched paper lacks a terminal
state. A paper must never disappear from the final report because processing
failed.

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
| `artifact_path` | string or null | yes | repository-relative when non-null | Location of the unmodified response; `null` only if no response artifact was produced. |
| `artifact_hash` | string or null | yes | 64 lowercase hexadecimal characters when non-null | SHA-256 of the response artifact bytes. |
| `validation_pass` | boolean | yes | — | Whether this exact response passed deterministic validation. |
| `retry_count` | integer | yes | `0` or `1` | Number of earlier attempts for the same role and paper. |
| `verdict_summary` | object or null | yes | critic events only | Counts of `supported`, `unsupported`, and `overclaimed` verdicts plus `relevance_justified`; `null` for reader events or an invalid critic response. |
| `tokens_in` | integer or null | yes | non-negative when known | Input tokens reported by the model provider. |
| `tokens_out` | integer or null | yes | non-negative when known | Output tokens reported by the model provider. |
| `cost_usd` | number or null | yes | non-negative when known | Provider-reported or deterministically calculated call cost in US dollars. |
| `error` | string or null | yes | non-empty when non-null | Visible dispatch, parsing, validation, or persistence error. |

`verdict_summary` contains exactly these fields: `supported`, `unsupported`,
and `overclaimed` as non-negative integers, and `relevance_justified` as a
boolean. Its three counts must sum to the length of the critic's `verdicts`.

If `artifact_path` is `null`, `artifact_hash` must also be `null`,
`validation_pass` must be `false`, and `error` must be non-null. If
`validation_pass` is `true`, both artifact fields must be non-null and `error`
must be `null`. Unknown token or cost values remain `null`; they are never
recorded as zero unless the provider actually reported zero.

## Artifact locations

| Artifact | Location |
|---|---|
| Fetched papers | `data/papers.json` |
| Invalid raw attempts | `data/attempts/{agent_run_id}/` |
| Reader records | `data/records/<arxiv-id>.json` |
| Critic records | `data/verdicts/<arxiv-id>.json` |
| Execution trace | `logs/trace.jsonl` |
| Ranked brief | `out/brief.md` |
| SQLite index | `data/triage.db` |

Canonical reader and critic filenames use a filesystem-safe form of the exact
versioned arXiv ID: replace `/` in legacy IDs with `__`; do not otherwise remove
the version suffix or alter the ID stored inside the JSON.

## Database mapping

Validated JSON artifacts are the evidence source of truth. SQLite is a
rebuildable query index, and `scripts/db.py` contains its SQL table definitions.
Fields absent from this mapping remain in the JSON artifact rather than causing
a database redesign in version `1.0`.

| Artifact field | SQLite table | SQLite column |
|---|---|---|
| `arxiv_id` | `papers` | `arxiv_id` |
| `title` | `papers` | `title` |
| `abstract` | `papers` | `abstract` |
| `published` | `papers` | `published` |
| `input_hash` | `papers` | `input_hash` |
| reader `arxiv_id` | `runs` | `arxiv_id` |
| reader `claims[].text` | `claims` | `text` |
| reader `claims[].source_span` | `claims` | `source_span` |
| reader `claims[].evidence_type` | `claims` | `evidence_type` |
| reader `claims[].provenance` | `claims` | `provenance` |
| reader `relevance` | `scores` | `relevance` |
| reader `importance` | `scores` | `importance` |
| reader `reason` | `scores` | `reason` |
| reader `extendable` | `scores` | `extendable` |
| critic `verdicts[].status` | `verdicts` | `status` |
| critic `verdicts[].reason` | `verdicts` | `reason` |

`schema_version`, strategic-relevance details, extension proposals, and workflow
terminal state remain artifact or report fields in version `1.0`; they are not
silently discarded from the canonical JSON.

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
