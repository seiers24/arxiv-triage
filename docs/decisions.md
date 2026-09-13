# Decisions


## Design Decision

* **Decision, stated simply:**

* **Why it was chosen:**

* **Alternatives Considered:**

* **Tradeoffs:**

* **Date made:**


## Sqlite/Json/JsonL combo

* **Why Sqlite/JSON/JSONL?:**
Sqlite was chosen along with Json to prioritize transparency, auditability, and cleanliness.  Sqlite stores run ids, reader claims, critic verdicts, relevance scores, and allow simple sorting and ranking by relevance and importance.  Additionally, sqlite holds paths to original JSON artifact and contains an input hash to verify that JSON artifact matches the original.  Sqlite will not replace original model artifacts, or be the only copy for a program run.

Json files are held inside the data/ directory to store frozen arXiv metadata and abstracts, paper-reader output, critic output, and invalid attempts.  Again, these files are directly located via their corresponding run that is stored as a sqlite row.

JSONL traces record one event per reader/critic attempt, and fields incclude input and outp hashes, artifact path, validation result, token/cost information, etc...

* **Alternatives Considered:**
I did consider simply storing artifacts as simple JSON files and creating an AGENTS.md in charge of locating these JSON files, however that violates my simplicitly rule, and puts an agent in charge of a task that could better be solved via deterministic code.

* **Tradeoffs:**
More plumbing for better transparency.
Potential disconnect between json files and sqlite row, hoever this is resolved via input/output hashes.

* Decision made on 09/07/2026

## Editable Objectives

As the project was designed, the tool could only be used for Micron.  However, this tool would be very beneficial for me in terms of personal research, and it may be beneficial to other people.  As such, editable objectives are required.  Obviously, this changes the evaluation criteria fundamentally, and that means that we need to be very careful on how we change the ranking system based on objective defined.  We need to decide how we rank, based on relevance, technical importance, extendability, etc...  Maybe we create weights for each category.

* **Why Editable Objectives?:**
Editable objectives, or shall I say, separate profiles, allow for the objective to change according to how Microns values change.  It also allows users to utilize this research tool for themselves, based on what they value as important or extendable.

* **Alternatives:**
The alternative here is basically the status of the project prior to the editable objectives plan.  Instead of having different "profiles" based on user preference, changing values, etc...  There would be one fixed objective, which is to find and rank papers that are relevant and extendable for Micron.

* **Tradeoffs:**
There are a couple of tradeoffs:
1. Each profile is mutable.  This means that the meaning of what is relevant to Micron can change over time.  This also means that the meaning of what is relevant or extendable with different profiles can change.
2. Storage.  Each run has to be differentiable to what profile it was run for.  Otherwise ranking results will be uninterpretable.

## Conservative abstract screening before full-text acquisition

* **Decision, stated simply:**
After deterministic query, normalization, and deduplication, a batched
`paper-screener` worker will assess frozen titles and abstracts against the
selected objective. Every candidate receives one visible state: `selected`,
`screened_out`, or `needs_review`. Only selected and needs-review candidates
proceed to full-text acquisition. Screening records and reasons are retained;
screened-out candidates are never silently deleted.

The orchestrator dispatches and validates screening work but does not perform
the semantic screening itself. Screening is batched to reduce model calls and
uses bounded concurrency. The evaluation set will include an audit sample of
screened-out papers and measure recall on human-priority papers.

* **Why it was chosen:**
Fetching, extracting, reading, and criticizing full papers is too expensive for
large candidate sets. Abstract screening removes clearly out-of-scope work
before those costs while keeping semantic judgment in a role-specific worker.
The `needs_review` state favors recall when an abstract is ambiguous.

* **Alternatives considered:**
- Read every full paper. Rejected because cost and latency scale poorly.
- Let the orchestrator read all abstracts. Rejected because it mixes control
  with paper judgment, expands the main context, and scales poorly.
- Use keyword filtering alone. Retained only for deterministic hard exclusions;
  rejected as the primary screen because it creates unmeasured false negatives.
- Reuse the full paper-reader for screening. Rejected because screening has a
  smaller input, different output contract, and batch-oriented cost model.

* **Tradeoffs:**
Screening adds a third worker role and can exclude a useful paper from full-text
analysis. Visible decisions, a conservative `needs_review` route, objective-
specific golden labels, and screened-out audits make that loss measurable.
No abstract-only method can guarantee that a paper is irrelevant.

* **Date made:** 2026-09-07

## Full-text source hierarchy

* **Decision, stated simply:**
For candidates that pass screening, deterministic scripts first try exact-
version arXiv HTML, then extract the arXiv PDF when HTML is absent or fails
quality checks, and finally create an explicitly degraded abstract-only packet
when reliable full text cannot be produced. Raw source bytes, extracted text,
tool versions, hashes, quality results, and fallback reasons are preserved.

The agent reads a validated frozen paper packet; it does not fetch or perform
basic document extraction. When HTML succeeds, the PDF may also be retained as
an audit artifact when available, but it is not required for the reader input.

* **Why it was chosen:**
HTML provides useful section structure when available, PDF covers papers
without reliable HTML, and a visible abstract fallback allows the run to finish
without pretending that full-text analysis occurred.

* **Alternatives considered:**
- Abstract-only reading. Rejected because it cannot support dependable claims
  about methods, baselines, limitations, or experimental setup.
- Give the reader a URL and let it fetch or extract. Rejected because source
  identity, caching, hashing, retries, and extraction failures would become
  difficult to reproduce.
- Use agent vision as the primary PDF extractor. Deferred because exact-span
  validation and deterministic replay are weaker; it may later be a bounded
  fallback for figures or extraction failures through a separate decision.
  Before this is even considered we need data on how many PDFs fail extraction
  on average.  This data helps us avoid scenarios in which we add this as a fallback
  but it becomes the only method of success.

* **Tradeoffs:**
Full-text acquisition adds storage, dependencies, quality gates, and failure
modes. HTML and PDF representations may differ, so every claim must bind to the
selected extracted representation and its raw-source hash. Abstract-only
packets must be labeled and gated in the final brief.

* **Date made:** 2026-09-07

## Minimal ReaderRecord for schema version 2.0

* **Decision, stated simply:**
The current `ReaderRecord` has one evidence-bearing collection: `claims`.
It retains the run, investigation, paper, source, and input identity fields plus
`problem`, `method`, `claims`, and `warnings`. The proposed parallel collections
`contributions`, `experimental_evidence`, `limitations`, `assumptions`, and
`focused_observations` are removed from the universal reader contract.

`claims` may be empty. An empty collection is preferable to requiring a reader
to invent a claim when the frozen source contains no extractable relevant
claim. When `claims` is empty, at least one `warnings` item explains why no
useful source-bound claim was extracted.

One project-owned validation gateway accepts the task and raw reader output;
the task embeds the hash-bound frozen source text. The gateway owns parsing,
structural validation, identity and hash
matching, cross-artifact checks, and exact source-locator reconstruction before
canonical promotion. The gateway may use small internal validators; callers do
not independently validate fragments of a reader record. Semantic support
remains the critic's judgment rather than a deterministic validator decision.

* **Why it was chosen:**
The removed collections duplicated information that can be expressed as typed
claims and created unnecessary contract, prompt, persistence, and correction
surface. One claims collection keeps evidence handling consistent and lets
downstream consumers rely on one representation.

* **Alternatives considered:**
- Define a detailed nested schema for all five proposed collections. Rejected
  because their meanings overlap and downstream consumers would need to
  reconcile redundant representations.
- Leave the five collections as arbitrary JSON. Rejected because arbitrary
  canonical data cannot be validated or consumed reliably.
- Require at least one claim. Rejected because it rewards fabricated filler
  when the source does not support a useful claim.

* **Tradeoffs:**
Component-specific observations are not first-class universal reader fields.
Components must guide which claims are extracted through reader focus and make
objective-specific judgments in their own later artifacts. The simpler public
gateway still requires documented internal checks to remain auditable.

* **Date made:** 2026-09-12

## Minimal exact worker and run contracts

* **Decision, stated simply:**
The current investigation schema has closed `CriticTask`, `CriticRecord`,
`ReviewerTask`,
`ReviewRecord`, `AgentRun`, `ValidationRecord`, `OutcomeRecord`, and
`TraceEvent` contracts. Reader, critic, and reviewer output each passes through
one project-owned validation gateway. Reader and critic tasks embed the exact
normalized `source_text`, bind it to the source-packet hash, and include it in
the task self-hash so tool-free workers receive all evidence they may inspect.

The critic emits one integer score for every declared `integer_0_5` criterion;
there is no unused label field. Human-review requirement derives from its
reason list. Corpus-accounting validity derives from the enforced equations.
Reviewer human-review items reference challenges by ID rather than duplicating
their text and evidence. Claim and verdict references include both paper and
claim ID so they remain unambiguous corpus-wide.

All self-hash fields use canonical JSON excluding only the object's own hash
field. Identifiers, repository-relative paths, canonical UTC timestamps,
finite numbers, run statuses, artifact pairs, and terminal outcome rules are
closed and mechanically validated. Empty frozen corpora remain valid.

* **Why it was chosen:**
The contracts preserve every identity and evidence relationship needed for
audit and deterministic persistence without asking agents to repeat facts that
scripts can derive. Self-contained dispatch inputs also make the no-tools
worker boundary executable rather than merely aspirational.

* **Alternatives considered:**
- Keep draft types or arbitrary nested reviewer data. Rejected because invalid
  canonical artifacts could not be rejected consistently.
- Serialize `label: null`, `human_review_required`, and `accounting_valid`.
  Rejected because they duplicate facts already fixed by score type, reasons,
  and arithmetic.
- Let workers read normalized source files. Rejected because workers are
  prohibited from using tools and the dispatched bytes would not fully identify
  their evidence input.

* **Tradeoffs:**
Tasks embed source text and canonical prior records, so dispatch payloads are
larger. Adding a new score type, source format, worker role, or report-gating
rule requires an explicit schema change rather than passing through an open
string or arbitrary object.

* **Date made:** 2026-09-13

## Invalid is terminal for a physical agent run

* **Decision, stated simply:**
`invalid` is a terminal outcome for one physical agent invocation. It means
bytes were returned but parsing or deterministic validation rejected them. It
is not followed by a redundant `agent_run.failed` event for the same attempt.
If the logical job remains retry-eligible, the workflow allocates a new
`agent_run_id` and increments `attempt_no`.

`failed` remains a distinct terminal outcome for an invocation that fails at
dispatch, transport, or another stage without producing output that reaches
validation. Exhausting the retry allowance can fail the logical job or its
paper without changing an earlier physical attempt from `invalid` to `failed`.

* **Why it was chosen:**
The terminal status precisely records why the physical attempt ended and keeps
one final outcome per attempt. Retry identity remains explicit instead of
reusing or mutating the invalid run.

* **Alternatives considered:**
Emit `agent_run.invalid` and then `agent_run.failed` for the same physical
attempt. Rejected because the second status loses precision and duplicates the
terminal transition.

* **Tradeoffs:**
Logical-job failure must be derived from its bounded attempts and recorded at
the paper or investigation level; it cannot be inferred by selecting only
physical runs whose status is `failed`.

* **Date made:** 2026-09-12

## Explicit blocked-review investigation state

* **Decision, stated simply:**
A valid `ReviewRecord` with `report_status: blocked` transitions the
investigation from `reviewing` to `review_blocked`. It does not transition to
the infrastructure-oriented `failed` state and it cannot proceed to rendering
until a later, explicitly defined workflow resolves the block.

* **Why it was chosen:**
A reviewer can successfully complete its job and correctly determine that an
honest report cannot yet be published. That outcome is materially different
from a crashed or contract-invalid investigation.

* **Alternatives considered:**
Map blocked review to `failed`. Rejected because it conflates a valid research
judgment with infrastructure or contract failure.

* **Tradeoffs:**
Status consumers must recognize another terminal-or-paused investigation
state, and resumption behavior must be defined before automatic recovery from
`review_blocked` is implemented.

* **Date made:** 2026-09-12

## Corpus means every frozen deduplicated discovered candidate

* **Decision, stated simply:**
The corpus is the complete frozen, deduplicated set of discovered paper
candidates. Provider hits and duplicate observations remain visible in the
append-only discovery ledger but do not create additional corpus entries.

Every corpus entry has exactly one membership disposition: `included`,
`excluded`, or `membership_unresolved`. Only included entries receive reader and
critic jobs. Included entries then have exactly one analysis outcome:
`complete`, `analysis_unresolved`, or `failed`.

`membership_unresolved` is reserved for discovery or identity cases that
cannot be routed. It does not replace the conservative screener's
`needs_review` result: a `needs_review` candidate is included and analyzed.

Reviewer and rendered accounting use these invariants:

```text
expected = total frozen corpus entries
expected = CorpusManifest.counts.discovered
expected = included + excluded + membership_unresolved
included = complete + analysis_unresolved + failed
```

All seven counts remain visible. Thus `expected` covers the whole corpus even
though analysis outcome accounting applies only to included entries.

* **Why it was chosen:**
This definition makes disappearance detectable from discovery through report
generation without manufacturing reader or critic outcomes for excluded
papers. Distinct membership and analysis unresolved counts also remove the
ambiguity of one overloaded `unresolved` label.

* **Alternatives considered:**
- Define corpus as included papers only. Rejected because discovered excluded
  and unresolved candidates would fall outside top-level corpus accounting.
- Require reader and critic outcomes for every discovered candidate. Rejected
  because exclusion is specifically intended to avoid that analysis work.
- Count raw provider results as corpus entries. Rejected because duplicate
  records for the same paper would inflate `expected`.

* **Tradeoffs:**
The system must preserve both raw discovery totals and deduplicated corpus
totals and must validate two equations rather than one. Membership disposition
and analysis outcome remain separate concepts in artifacts, storage, and
reports.

* **Date made:** 2026-09-12
