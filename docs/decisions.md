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
