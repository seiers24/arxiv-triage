# Full-text triage implementation plan

## Goal

Replace the abstract-only reader input with a reproducible full-text pipeline
while avoiding full-source acquisition and model calls for clearly out-of-scope
papers.

The target flow is:

```text
query + objective
  -> deterministic metadata/abstract fetch and version deduplication
  -> batched abstract screening: selected | screened_out | needs_review
  -> selected/needs_review only: exact-version HTML acquisition
  -> PDF extraction when HTML is unavailable or unreliable
  -> explicit abstract-only packet when both full-text routes fail
  -> reader -> validation -> critic -> bounded re-read decision
  -> deterministic persistence, ranking, and brief
```

No candidate or paper disappears. The brief reports candidate, screened-out,
selected, abstract-only, complete, unresolved, and failed counts.

## Non-goals

- OCR, table reconstruction, or perfect mathematical notation in the first
  full-text version.
- Agent-controlled network fetching or basic document extraction.
- Unbounded agent fan-out or retries.
- Treating abstract screening as proof that a paper is irrelevant.
- Comparing scores created under different objective hashes.

## 1. Freeze decisions and role boundaries

### Work

- Record conservative abstract screening and the HTML/PDF/abstract hierarchy in
  `docs/decisions.md`.
- Keep repository-wide constraints in `AGENTS.md` and move orchestrator-specific
  responsibilities to `docs/roles/orchestrator.md`.
- Add `.claude/agents/paper-screener.md` as a third, bounded worker role. It
  receives batches of frozen titles and abstracts plus one objective and emits
  screening records only.
- Do not let the orchestrator personally screen abstracts; it dispatches,
  validates, and routes screening results.

### Screening policy

Each query candidate must receive exactly one state:

- `selected`: the abstract contains a defensible objective connection.
- `screened_out`: the abstract is clearly outside the objective or matches an
  explicit exclusion.
- `needs_review`: the abstract is ambiguous, incomplete, or plausibly relevant.

Both `selected` and `needs_review` proceed to source acquisition. Screening
records include the candidate ID, objective hash, state, concise reason, and
any abstract spans supporting the decision. A deterministic cap may limit a
run only after these states and reasons have been preserved.

The screener is a conservative gate, not a ranker. It may emit `screened_out`
only when the supplied title and abstract establish an explicit exclusion or
leave no plausible connection to the objective. Missing experimental detail,
an unclear contribution, or uncertainty about the connection routes the
candidate to `needs_review`; absence of detail in an abstract is not evidence
that the full paper is irrelevant.

A processing budget must not relabel an otherwise selected candidate as
`screened_out`. Candidates beyond a deterministic run cap remain visibly
deferred for a later run. Evaluation uses a predeclared, deterministically
selected audit sample of `screened_out` candidates to measure false negatives.

### Gate

The role index has no duplicated prompts, the new worker is authorized by a
recorded decision, and a human can identify who owns every workflow judgment.

## 2. Define schema version 2.0

Update `docs/schema.md` before code or prompts.

### New source contracts

Define:

- `CandidatePaper`: frozen metadata and abstract used for screening.
- `ScreeningDispatch` and `ScreeningRecord`.
- `RawSourceArtifact`: format, exact-version URL, local path, byte hash, size,
  acquisition timestamp, and error when applicable.
- `ExtractionReport`: extractor name/version, status, warnings, character and
  section counts, abstract-match result, and fallback reason.
- `SourceParagraph`: stable paragraph ID, text, section ID, and PDF page when
  applicable.
- `FrozenPaperPacket`: metadata, abstract, selected source representation,
  ordered sections/paragraphs, raw-source hashes, extraction report,
  `source_scope`, and `packet_hash`.
- `SourceLocator`: selected source hash, section ID, paragraph ID, and optional
  page number.

Use these source values:

- `source_scope`: `full_text` or `abstract_only`.
- `source_format`: `html`, `pdf_text`, or `abstract`.
- `extraction_status`: `passed`, `degraded`, or `failed`.

### Reader and critic changes

- Replace `FrozenPaper` in `ReaderDispatch` with `FrozenPaperPacket`.
- Bind every reader and critic artifact to `packet_hash` and `objective_hash`.
- Add `source_locator` to each non-null claim span and validate it against the
  selected paragraph.
- Require the reader to use the abstract for its initial problem-and-method
  synopsis, then verify and correct that synopsis against the selected full
  text before returning it. For an abstract-only packet, require an explicit
  statement that full-paper verification was unavailable.
- Require the reader to report `source_scope`; prohibit strong judgments about
  unobserved methods, baselines, limitations, or novelty for abstract-only
  packets.
- Add an `extension_assessment` to `CriticRecord` with `justified`, `testable`,
  `objective_aligned`, and `reason` fields.
- Extend trace roles to include `screener` and add acquisition/extraction
  events that do not pretend to be model dispatches.
- Add candidate screening and source-preparation states separately from paper
  analysis terminal states.

### Storage changes

- Preserve editable objectives and frozen objective snapshots as in version
  `1.0`.
- Store raw HTML/PDF files under content-addressed source paths.
- Store extracted packets under `data/packets/<packet-hash>.json`.
- Store screening artifacts by objective hash and screening run ID.
- Add SQLite objective, candidate, screening, source, and packet indexes while
  keeping JSON artifacts as the source of truth.

### Gate

The schema explains every field and state, all examples are valid JSON, and no
version `1.0` artifact can be mistaken for a version `2.0` artifact.

## 3. Update Pydantic validation

### Work

- Implement the new contracts in `scripts/validate.py` with unknown fields
  forbidden and strict scalar types.
- Retain canonical objective and paper hashing; add raw-source and packet hash
  validation.
- Validate unique section and paragraph IDs, valid page numbers, source
  locators, exact normalized spans, and screening coverage.
- Validate that every query candidate has exactly one screening result.
- Validate that only `selected` and `needs_review` candidates receive packets.
- Validate critic claim coverage and the new extension assessment.
- Preserve invalid raw artifacts and return structured errors without partial
  SQLite ingestion.

### Tests

- Valid HTML, PDF-text, and abstract-only packets.
- Source hash and packet hash mismatches.
- Missing, duplicate, and invalid paragraph locators.
- Exact span absent from the located paragraph.
- Screening ID, objective hash, and coverage mismatches.
- Abstract-only output that claims unobserved full-paper details.
- Missing or inconsistent extension assessment.
- Unknown fields and schema-version mismatches.

### Gate

All schema invariants have deterministic tests, and the existing version `1.0`
fixtures are either migrated explicitly or rejected clearly.

## 4. Implement deterministic acquisition and extraction

### Candidate fetch

Keep `scripts/fetch.py` responsible for querying arXiv, normalizing versioned
IDs, deduplicating, sorting, and freezing metadata plus abstracts. It does not
download full text before screening.

### Source acquisition

Add `scripts/fetch_source.py`:

1. Receive one selected candidate and explicit output directory.
2. Attempt exact-version official arXiv HTML.
3. Validate that the response is a paper document for the requested version.
4. If HTML is absent or invalid, download the exact-version PDF.
5. Preserve raw bytes and SHA-256 hashes; never overwrite a different hash.
6. Use bounded timeouts, response-size limits, retries, and visible errors.

When HTML passes, optionally retain the PDF as an audit artifact if available;
HTML remains the selected extraction source. Full-source acquisition failures
must not erase the frozen abstract.

### Extraction

Add `scripts/extract.py`:

- Parse HTML into ordered sections and paragraphs without a model.
- Extract PDF text with page boundaries and stable paragraph IDs without a
  model.
- Normalize only documented whitespace; preserve original extracted text used
  for source-span checks.
- Record extractor name, dependency version, warnings, and counts.
- Produce canonical packet JSON and its hash.

### Quality gate and fallback

Deterministically check:

- Requested arXiv ID/version matches the acquired source.
- Extracted content is nonempty and exceeds a documented minimum.
- The frozen abstract matches or substantially overlaps the extracted source.
- Section/paragraph IDs are unique and ordered.
- Corrupt-character rate is below a documented limit.
- The response is not an error, consent, or rate-limit page.

If HTML fails, try PDF. If PDF acquisition or extraction fails its quality
gate, emit an `abstract_only` packet with all failure reasons and raw artifacts
preserved. Do not call an agent to repair extraction in version `2.0`.

### Fixtures and tests

- One representative arXiv HTML fixture.
- One PDF fixture with multiple pages and headings.
- Missing HTML with valid PDF fallback.
- Corrupt or image-only PDF producing abstract fallback.
- Version mismatch and HTTP error fixtures.
- Byte-stable packet generation from identical inputs.

### Gate

All fallback routes run offline from fixtures, and repeated extraction produces
identical packet hashes and paragraph IDs.

## 5. Complete workers and the orchestration skill

### Worker definitions

- Create `.claude/agents/paper-screener.md` with a batch-size limit, conservative
  state rubric, exact output contract, and no authority to fetch or rank. Its
  default under material uncertainty is `needs_review`, not `screened_out`.
- Update `.claude/agents/paper-reader.md` to consume `FrozenPaperPacket`, cite
  paragraph/page locators, draft the problem and method from the abstract,
  verify and correct them against full text, disclose `source_scope`, and avoid
  abstract-only overreach.
- Complete `.claude/agents/critic.md` to receive the identical packet,
  objective, and validated reader record; check claim spans, evidence type,
  objective-relevance chain, and extension proposal independently.

### Create `.claude/skills/triage-topic/SKILL.md`

The skill is the executable runbook for the main session acting under
`docs/roles/orchestrator.md`. It must specify:

1. Required query, objective profile, limits, and concurrency inputs.
2. Objective validation and frozen snapshot creation.
3. Deterministic candidate fetch.
4. Bounded, batched screener dispatch and complete screening validation.
5. Full-source acquisition only for `selected` and `needs_review` candidates.
6. Packet validation and visible abstract-only routing.
7. Bounded reader dispatch, validation, and one correction retry for malformed
   output.
8. Bounded critic dispatch and one source-bound reader re-read on a substantive
   objection.
9. Trace and SQLite persistence after each attempt without rewriting artifacts.
10. Deterministic ranking, report generation, and terminal-state checks.

The skill must use explicit counters, preserve independent progress after a
failure, and never launch all paper workers simultaneously. It references the
human-readable orchestrator role rather than duplicating it.

### Gate

Each worker can produce a schema-valid artifact from an offline fixture, and
the skill names every command, input, output, concurrency bound, retry bound,
and failure route.

## 6. Extend evaluation and prove the pipeline

### Evaluation additions

Update `docs/evaluation.md` with:

- Screening recall on human-priority papers.
- False-negative review from a fixed sample of `screened_out` candidates.
- Screening cost per candidate and batch.
- HTML and PDF extraction pass rates.
- Abstract-match, locator, and exact-span validity.
- Frequency and reason for abstract-only fallback.
- Reader quality on full text versus abstract-only input.
- Critic accuracy for claims, relevance, and extension assessments.
- End-to-end latency, tokens, cost, retries, unresolved items, and failures.

Initial gates should include 100% visible screening coverage, 100% valid source
locators, 100% detection of planted unsupported claims, and no silent fallback.
Do not claim a natural screening error rate from planted cases.

### End-to-end demonstration

Run at least five mixed candidates:

- One accepted through HTML.
- One accepted through PDF fallback.
- One explicit abstract-only fallback.
- One screened out.
- One ambiguous candidate routed through `needs_review`.

Verify that every candidate is represented in artifacts and counts, every
displayed claim resolves to its frozen source span, and the brief can be rebuilt
without a model call.

### Final gate

The README quickstart works as written; tests pass from a clean shell; a human
can trace any ranked claim through objective, screening decision, raw source,
extraction packet, reader record, critic verdict, and final score.

## Implementation order

Complete the six stages in order. Do not begin agent or extraction code until
the version `2.0` schema is frozen, and do not tune screening or ranking after
seeing the demonstration results. If time is constrained, reduce the candidate
count—not provenance, validation, screening visibility, source hashes, or
fallback reporting.
