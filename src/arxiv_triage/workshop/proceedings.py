"""Deterministic identities from frozen CVF workshop proceedings pages."""

from __future__ import annotations

import html
import re
from collections.abc import Iterable
from urllib.parse import urljoin

from arxiv_triage.models import PaperIdentity, sha256_json

from .resolve import normalized_title


_PAPER = re.compile(
    r'<dt\s+class="ptitle"[^>]*>.*?<a\s+href="(?P<html>[^"]+)">'
    r"(?P<title>.*?)</a></dt>(?P<body>.*?)(?=<dt\s+class=|</dl>)",
    re.DOTALL | re.IGNORECASE,
)
_AUTHOR = re.compile(
    r'<input\s+type="hidden"\s+name="query_author"\s+value="([^"]+)">',
    re.IGNORECASE,
)
_PDF = re.compile(r'<a\s+href="([^"]+paper\.pdf)">pdf</a>', re.IGNORECASE)
_ARXIV = re.compile(r'<a\s+href="(https://arxiv\.org/abs/([^"?#]+))">arXiv</a>', re.IGNORECASE)
_TAGS = re.compile(r"<[^>]+>")


def _text(value: str) -> str:
    return " ".join(html.unescape(_TAGS.sub("", value)).split())


def parse_cvf_proceedings_pages(
    pages: Iterable[tuple[str, bytes]],
) -> list[PaperIdentity]:
    """Parse exact paper identities and bound PDF URLs from frozen CVF pages."""

    identities: list[PaperIdentity] = []
    seen_titles: set[str] = set()
    for page_url, response in pages:
        try:
            source = response.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("CVF proceedings page must be valid UTF-8") from exc
        matches = list(_PAPER.finditer(source))
        if not matches:
            raise ValueError("CVF proceedings page contains no paper entries")
        for match in matches:
            title = _text(match.group("title"))
            title_key = normalized_title(title)
            if title_key in seen_titles:
                raise ValueError(f"duplicate CVF proceedings title: {title}")
            seen_titles.add(title_key)
            body = match.group("body")
            authors = [_text(value) for value in _AUTHOR.findall(body)]
            if not authors:
                raise ValueError(f"CVF proceedings entry has no authors: {title}")
            pdf_match = _PDF.search(body)
            if pdf_match is None:
                raise ValueError(f"CVF proceedings entry has no paper PDF: {title}")
            html_url = urljoin(page_url, html.unescape(match.group("html")))
            pdf_url = urljoin(page_url, html.unescape(pdf_match.group(1)))
            identifiers: list[dict[str, str]] = [
                {
                    "scheme": "proceedings",
                    "value": html_url,
                    "url": pdf_url,
                }
            ]
            arxiv_match = _ARXIV.search(body)
            if arxiv_match is not None:
                identifiers.append(
                    {
                        "scheme": "arxiv",
                        "value": arxiv_match.group(2),
                        "url": arxiv_match.group(1),
                    }
                )
            payload = {
                "schema_version": "2.0",
                "paper_id": f"paper-cvf-{sha256_json({'title': title_key})[:16]}",
                "title": title,
                "authors": authors,
                "published": None,
                "identifiers": identifiers,
                "identity_status": "resolved_exact",
            }
            payload["identity_hash"] = sha256_json(payload)
            identities.append(PaperIdentity.model_validate(payload))
    return identities


__all__ = ["parse_cvf_proceedings_pages"]
