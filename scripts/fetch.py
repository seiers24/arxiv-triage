#!/usr/bin/env python3
"""Fetch and freeze a deterministic, bounded arXiv paper set.

The output is a JSON array of frozen-paper records as defined in
``docs/schema.md``.  It deliberately contains no fetch timestamp: given the
same source results, selection, ordering, and input hashes are byte-stable.

Examples:

    uv run scripts/fetch.py "KV cache compression"
    uv run scripts/fetch.py "KV cache compression" --limit 10 \
        --output data/papers.json
    uv run scripts/fetch.py "fixture smoke test" \
        --fixture tests/fixtures/arxiv-results.json --no-db
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import arxiv


SCHEMA_VERSION = "1.0"
DEFAULT_LIMIT = 15
DEFAULT_OUTPUT = Path("data/papers.json")
DEFAULT_DB = Path("data/triage.db")

# Includes modern IDs (2601.01234v1) and legacy IDs (cs/0112017v3).  The
# suffix is intentionally required: workers must receive the exact revision
# whose abstract was frozen.
ARXIV_ID_RE = re.compile(
    r"^(?P<base>(?:[a-z][a-z-]*(?:\.[A-Za-z-]+)?/)?(?:\d{4}\.\d{4,5}|\d{7}))"
    r"v(?P<version>[1-9]\d*)$"
)


def canonical_json(value: object) -> str:
    """Serialize JSON in the canonical form specified by the schema."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def input_hash(record: Mapping[str, object]) -> str:
    """Return the frozen-paper SHA-256, excluding ``input_hash`` itself."""
    payload = {key: value for key, value in record.items() if key != "input_hash"}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def normalize_arxiv_id(value: str) -> tuple[str, str, int]:
    """Return canonical versioned ID, unversioned dedupe key, and version.

    arXiv result objects normally expose an ``abs`` URL.  Fixtures and tests
    may instead provide an ID directly, so both forms are accepted.
    """
    candidate = value.strip()
    if candidate.lower().startswith("arxiv:"):
        candidate = candidate[6:].strip()

    parsed = urlparse(candidate)
    if parsed.scheme or parsed.netloc:
        path = parsed.path.strip("/")
        for prefix in ("abs/", "pdf/"):
            if path.startswith(prefix):
                path = path[len(prefix) :]
                break
        candidate = path.removesuffix(".pdf")

    match = ARXIV_ID_RE.fullmatch(candidate)
    if not match:
        raise ValueError(
            f"arXiv ID must be a versioned modern or legacy ID; got {value!r}"
        )
    base = match.group("base")
    version = int(match.group("version"))
    return f"{base}v{version}", base, version


def rfc3339(value: datetime | str | None, field: str, *, nullable: bool) -> str | None:
    """Canonicalize a supplied arXiv timestamp to second-precision UTC."""
    if value is None:
        if nullable:
            return None
        raise ValueError(f"{field} is missing")
    if isinstance(value, str):
        text = value.strip()
        if not text:
            if nullable:
                return None
            raise ValueError(f"{field} is empty")
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} is not an RFC 3339 timestamp: {value!r}") from exc
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise ValueError(f"{field} is not a timestamp: {value!r}")

    if parsed.tzinfo is None:
        # arXiv's client returns timezone-aware values.  Fixtures without a
        # timezone are rejected rather than silently assigning one.
        raise ValueError(f"{field} must include a timezone: {value!r}")
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def nonempty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return nonempty_string(value, field)


def authors_from(value: object) -> list[str]:
    if not isinstance(value, list):
        raise ValueError("authors must be a list")
    authors: list[str] = []
    for author in value:
        name = author.get("name") if isinstance(author, Mapping) else author
        authors.append(nonempty_string(name, "author name"))
    if not authors:
        raise ValueError("authors must contain at least one author")
    return authors


def freeze_result(source: Mapping[str, object]) -> dict[str, object]:
    """Convert a live-client or fixture result into a frozen schema record."""
    entry_id = nonempty_string(source.get("entry_id"), "entry_id")
    arxiv_id, _base, _version = normalize_arxiv_id(entry_id)
    record: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "arxiv_id": arxiv_id,
        "title": nonempty_string(source.get("title"), "title"),
        "abstract": nonempty_string(source.get("summary"), "summary"),
        "authors": authors_from(source.get("authors")),
        "published": rfc3339(source.get("published"), "published", nullable=False),
        "updated": rfc3339(source.get("updated"), "updated", nullable=True),
        "journal_reference": optional_string(source.get("journal_ref"), "journal_ref"),
        "doi": optional_string(source.get("doi"), "doi"),
    }
    record["input_hash"] = input_hash(record)
    return record


def client_source(result: arxiv.Result) -> dict[str, object]:
    """Adapt the arxiv package's result object to the fixture input shape."""
    return {
        "entry_id": result.entry_id,
        "title": result.title,
        "summary": result.summary,
        "authors": [{"name": author.name} for author in result.authors],
        "published": result.published,
        "updated": result.updated,
        "journal_ref": result.journal_ref,
        "doi": result.doi,
    }


def deduplicate_and_select(results: Iterable[Mapping[str, object]], limit: int) -> list[dict[str, object]]:
    """Keep the newest revision per paper, then sort by publication and ID.

    Sorting happens before applying the limit so a service's pagination order
    cannot alter which duplicate-free papers are selected from a fixed result
    set.  For a duplicate with the same revision, canonical JSON provides a
    deterministic final choice.
    """
    by_base: dict[str, tuple[int, dict[str, object]]] = {}
    for result in results:
        frozen = freeze_result(result)
        _full, base, version = normalize_arxiv_id(str(frozen["arxiv_id"]))
        previous = by_base.get(base)
        if previous is None or version > previous[0] or (
            version == previous[0] and canonical_json(frozen) < canonical_json(previous[1])
        ):
            by_base[base] = (version, frozen)

    papers = [item[1] for item in by_base.values()]
    # Python's sort is stable, so the first sort gives ascending ID ties while
    # the second gives newest original submission first.
    papers.sort(key=lambda paper: str(paper["arxiv_id"]))
    papers.sort(key=lambda paper: str(paper["published"]), reverse=True)
    return papers[:limit]


def load_fixture(path: Path) -> list[Mapping[str, object]]:
    """Load cached arXiv-like result records for network-free tests and demos."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"fixture not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"fixture is not valid JSON: {path}: {exc}") from exc
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError("fixture must be a JSON array of arXiv result objects")
    return payload


def fetch_live(query: str, limit: int) -> list[Mapping[str, object]]:
    """Fetch enough candidates to compensate for version-level duplicates."""
    search = arxiv.Search(
        query=query,
        max_results=limit * 3,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending,
    )
    client = arxiv.Client()
    return [client_source(result) for result in client.results(search)]


PAPERS_TABLE = """
CREATE TABLE IF NOT EXISTS papers (
    arxiv_id    TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    abstract    TEXT NOT NULL DEFAULT '',
    published   TEXT,
    fetched_at  TEXT NOT NULL,
    input_hash  TEXT NOT NULL
)
"""


def upsert_papers(db_path: Path, papers: Iterable[Mapping[str, object]]) -> None:
    """Populate the rebuildable paper index without involving an agent."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(PAPERS_TABLE)
        connection.executemany(
            """
            INSERT INTO papers (arxiv_id, title, abstract, published, fetched_at, input_hash)
            VALUES (:arxiv_id, :title, :abstract, :published, :fetched_at, :input_hash)
            ON CONFLICT(arxiv_id) DO UPDATE SET
                title = excluded.title,
                abstract = excluded.abstract,
                published = excluded.published,
                fetched_at = excluded.fetched_at,
                input_hash = excluded.input_hash
            """,
            [{**paper, "fetched_at": fetched_at} for paper in papers],
        )


def write_output(path: Path, papers: list[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(papers, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch and freeze a bounded arXiv result set.")
    parser.add_argument("query", help="arXiv API query string")
    parser.add_argument("--limit", type=positive_int, default=DEFAULT_LIMIT, help="papers to retain (default: 15)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help=f"frozen-paper JSON path (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"SQLite index path (default: {DEFAULT_DB})")
    parser.add_argument("--no-db", action="store_true", help="do not upsert frozen papers into SQLite")
    parser.add_argument("--fixture", type=Path, help="cached result JSON; skips the network")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        sources = load_fixture(args.fixture) if args.fixture else fetch_live(args.query, args.limit)
        papers = deduplicate_and_select(sources, args.limit)
        if not papers:
            raise ValueError("arXiv returned no usable papers for this query")
        write_output(args.output, papers)
        if not args.no_db:
            upsert_papers(args.db, papers)
    except (arxiv.ArxivError, OSError, ValueError, sqlite3.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps({"papers": len(papers), "output": str(args.output), "database": None if args.no_db else str(args.db)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
