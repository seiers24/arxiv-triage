# Plan 2: Workshop Analysis

## Goal

Build the first complete component on the core investigation platform. Given an
authoritative workshop page or a workshop name, enumerate the accepted-paper
population, resolve and fetch every available paper, extract and verify its
evidence, rank papers against a frozen workshop objective profile, and produce
a complete table plus a defensible top tier.

The first acceptance fixture is the Third Workshop on Efficient and On-Device
Generation (EDGE), CVPR 2026:

- authoritative page: `https://cvpr26-edge.github.io/`
- publicly enumerated population: 15 accepted papers
- tracks: 10 long papers and 5 short papers
- only long papers are declared for inclusion in the CVPR proceedings

The public page does not establish the population of rejected or withdrawn
submissions. Version 1 of this component therefore promises complete accounting
of **accepted papers**, not all submitted papers.

## Dependency on Plan 1

This plan begins only after the core schemas, source packets, state machine,
trace, database index, base agents, reviewer, validation, ranker, and renderer
exist and pass their synthetic tests.

Workshop code adds component artifacts and skills. It does not fork the base
paper or claim schemas.

## Component artifacts

### `WorkshopSpec`

- canonical workshop name, ordinal, venue, year, and dates
- authoritative program/proceedings URL
- submission venue identifier when available
- requested population: initially `accepted`
- track definitions
- source precedence

### `WorkshopEntry`

- ordinal and stable entry ID
- exact displayed title and authors
- track, poster/session metadata, and acceptance status
- exact listing source span and source hash
- resolved `paper_id` or `null`
- resolution method, confidence, and status
- visible failure or human-review reason

### `WorkshopCorpusManifest`

- authoritative source request/response hashes
- declared, extracted, resolved, analyzed, unresolved, and failed counts
- every paper entry
- excluded non-paper entries and reasons
- completeness status

## Acquisition pipeline

Implement two explicitly separate test paths.

### Path A: known authoritative URL

1. Fetch the supplied URL directly and freeze the response.
2. If direct extraction fails, try Tavily Extract basic once, then advanced once.
3. Parse only the accepted-paper section.
4. Exclude speakers, schedule talks, organizers, sponsors, and navigation links.
5. Preserve tracks and listing spans.

This path proves corpus extraction independently of web search.

### Path B: workshop name only

1. Use Tavily Search to locate candidate official pages.
2. Disable generated answers and automatic parameter selection.
3. Prefer official conference, workshop, OpenReview, and proceedings domains.
4. Select an authoritative source using explicit provenance rules.
5. Run the exact same pipeline as Path A.

Path A and Path B must produce the same corpus membership. Tavily results find
the authoritative page; they never define workshop membership directly.

## Paper identity resolution

For each workshop entry, attempt in order:

1. Exact structured-venue match, such as OpenReview.
2. Exact normalized arXiv-title match.
3. DOI or official proceedings match.
4. Exact-title web search.
5. Normalized-title plus author-overlap match.
6. Human review.

Use `resolved_exact`, `resolved_probable`, `ambiguous`, or `not_found`. Only an
exact resolution proceeds automatically. A search result may resolve an entry
but may not add a new workshop member.

## Workshop objective profile

Create the initial profile before any paper analysis. Its scope comes from the
frozen workshop call for papers rather than model background knowledge.

Initial dimensions:

| Dimension | Use |
|---|---|
| Workshop fit | Gate: contribution must address at least one CFP topic |
| Evidence strength | Quality and completeness of supporting evaluation |
| Efficiency result | Improvement against a meaningful baseline and metric |
| Deployment realism | Strength of evidence for the claimed target environment |
| Corpus distinctiveness | Difference from the other accepted papers |
| Extension leverage | Availability of a concrete, testable next step |

Define anchors for every ordinal score. Do not force a fixed number of winners.
The profile defines top-tier gates and thresholds, and the deterministic ranker
applies them.

Corpus distinctiveness belongs to the reviewer because it requires the complete
corpus. Readers and per-paper critics may identify candidate distinctions but
cannot declare them corpus-wide.

## Workshop component skill

Create:

```text
.claude/skills/workshop-analysis/
  SKILL.md
  references/
    acquisition.md
    reader-focus.md
    critic-rubric.md
    reviewer-rubric.md
    output-contract.md
```

### Reader overlay

Require focused extraction of:

- CFP topic addressed
- efficiency mechanism
- training versus inference claim
- baselines, metrics, and numeric results
- hardware, simulator, dataset, and workload
- latency, throughput, memory, energy, and quality tradeoffs
- whether on-device behavior is measured, modeled, or motivational only

The overlay cannot make the reader rank or verify its own output.

### Critic overlay

Require the critic to test:

- whether the workshop connection follows from supported claims
- whether evidence modality matches the source
- whether hardware and deployment claims describe actual measurements
- whether efficiency comparisons preserve baseline, metric, and scope
- whether missing evaluation is visible
- whether uncertainty requires human review

### Reviewer overlay

Require the reviewer to test:

- exact corpus accounting
- top-tier gates and deterministic arithmetic
- comparative and distinctiveness claims against all accepted papers
- treatment of short versus long papers without assuming length means quality
- exclusion of unresolved evidence from strong conclusions
- report wording that separates paper advertising, critic-supported findings,
  corpus-relative judgments, and analyst inference

## Workflow

```text
workshop input
  -> authoritative source resolution
  -> accepted-paper extraction
  -> frozen corpus manifest
  -> paper identity/source resolution
  -> one reader per resolved paper
  -> one critic per valid reader record
  -> terminal accounting for all 15 entries
  -> deterministic component scores
  -> one corpus reviewer
  -> deterministic table and report rendering
```

Unresolved source identities remain in the paper table and count toward the
failed or unresolved total. They are never removed to improve apparent coverage.

## Golden fixture and tests

Create a manually verified fixture from the official EDGE page before comparing
model output. It contains the 15 displayed titles, authors, tracks, poster
numbers, and exact page spans.

### Acquisition acceptance tests

- accepted-paper recall: 15/15
- accepted-paper precision: 15/15
- correct long/short track: 15/15
- invited talks classified as papers: 0
- organizers or sponsors classified as papers: 0
- duplicate papers: 0
- silently dropped entries: 0
- known-URL and name-only membership sets are identical
- the page's internal "Second Workshop" typo does not change workshop identity

### Identity and source tests

- exact matches resolve automatically
- title collisions require author or identifier confirmation
- probable and ambiguous matches enter human review
- unavailable full text remains visible
- source hashes and locators reproduce every reader span

### Reader and critic tests

- distinguish real-device measurements from simulation or motivation
- preserve baseline, metric, and experimental scope in result claims
- reject planted hardware and performance overclaims
- flag workshop relevance with no supported claim references
- record missing evidence rather than infer it

### Ranking and reviewer tests

- deterministic score reproduction from the frozen profile
- no forced top-k when fewer papers pass top-tier gates
- every displayed ranking reason cites supported claim IDs
- corpus-distinctiveness findings cite comparison records
- unresolved papers cannot silently become top-tier
- reviewer catches a planted unsupported comparative conclusion

### Human evaluation

Before viewing model scores, hand-label the 15 papers using the same anchored
profile. Report:

- top-tier precision and recall
- rank correlation
- per-dimension exact and within-one agreement
- unsupported factual or relevance statements
- uncertainty precision: how often escalated items genuinely need review
- reader-only versus reader-plus-critic error counts

The critical safety metric is zero unsupported factual or relevance claims
presented as verified.

## Output

Produce:

- complete accepted-paper CSV and Markdown table
- source-resolution and processing accounting
- per-paper evidence matrix
- top-tier list with deterministic score breakdown
- paper-advertised versus critic-supported findings
- corpus-relative distinctiveness findings
- extension opportunities labeled as inference
- unresolved, failed, and human-review sections
- full run and component-skill provenance

Do not use `revolutionary` as a stored boolean. Use supported dimensions and
corpus-relative explanations.

## Implementation sequence

1. Add workshop schemas and fixture.
2. Implement known-URL fetch and accepted-section parser.
3. Implement structured identity resolution and source fetching.
4. Write the workshop objective profile and skill overlays.
5. Run all 15 papers through reader and critic.
6. Implement workshop scoring and corpus reviewer rubric.
7. Render and evaluate the known-URL report.
8. Add Tavily name-only discovery.
9. Prove both discovery paths yield identical membership.

## Definition of done

- The official EDGE accepted population is recovered exactly.
- Every entry has a terminal state and appears in the report.
- Every factual and relevance statement traces to critic-supported evidence.
- Top-tier membership is reproducible from the frozen profile.
- Cross-paper claims pass corpus review or are visibly challenged.
- Known-URL and name-only discovery produce the same accepted-paper corpus.
