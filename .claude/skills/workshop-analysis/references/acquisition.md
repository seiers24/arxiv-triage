# Acquisition rules

## Membership

Parse only the accepted-paper section of the frozen authoritative page.
Preserve exact displayed title, authors, track, poster/session metadata, and
listing span. Exclude speakers, schedule talks, organizers, sponsors, and
navigation. Validate declared count before freezing the corpus.

Known authoritative URL routing is direct fetch, then at most one Tavily basic
extract and one Tavily advanced extract if those routes are available. Name-only
routing may use bounded Tavily search solely to find an authoritative page; it
must then use the same extraction path. Provider output never defines
membership.

## Identity and source precedence

Try exact structured-venue identity, exact normalized arXiv title, official
proceedings, exact-title search, title plus author confirmation, then human
review. Only `resolved_exact` proceeds automatically.

For an exact identity, prefer frozen full text in this order:

1. exact-version arXiv HTML;
2. exact-version arXiv PDF text;
3. official proceedings PDF text;
4. exact OpenReview PDF text;
5. frozen abstract as an explicitly degraded fallback.

Every selected URL must already be bound to the exact identity. Preserve failed
response bytes and extraction errors. An unavailable source produces a visible
terminal failure; continue other papers.
