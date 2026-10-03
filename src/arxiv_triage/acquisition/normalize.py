"""Deterministic normalization of HTML and extracted plain text."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser


_BLANK_LINES = re.compile(r"\n{3,}")
_SPACE = re.compile(r"[ \t\f\v]+")


@dataclass(frozen=True, slots=True)
class NormalizedSection:
    heading: str
    start_char: int
    end_char: int


@dataclass(frozen=True, slots=True)
class NormalizedSource:
    text: str
    sections: tuple[NormalizedSection, ...]


def normalize_plain_text(value: str, *, heading: str = "Document") -> NormalizedSource:
    """Normalize line endings and horizontal whitespace without rewriting words."""

    value = unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n")
    lines = [_SPACE.sub(" ", line).strip() for line in value.split("\n")]
    text = _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()
    if not text:
        raise ValueError("normalized source text must not be empty")
    return NormalizedSource(text, (NormalizedSection(heading, 0, len(text)),))


class _BlockParser(HTMLParser):
    _BLOCK_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "pre"})
    _IGNORED_TAGS = frozenset({"script", "style", "noscript", "svg"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, str]] = []
        self._tag: str | None = None
        self._parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in self._IGNORED_TAGS:
            self._ignored_depth += 1
        elif not self._ignored_depth and tag in self._BLOCK_TAGS:
            self._flush()
            self._tag = tag

    def handle_endtag(self, tag: str) -> None:
        if tag in self._IGNORED_TAGS and self._ignored_depth:
            self._ignored_depth -= 1
        elif not self._ignored_depth and self._tag == tag:
            self._flush()

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth and self._tag is not None:
            self._parts.append(data)

    def close(self) -> None:
        super().close()
        self._flush()

    def _flush(self) -> None:
        if self._tag is not None:
            text = _SPACE.sub(" ", " ".join(self._parts)).strip()
            if text:
                kind = "heading" if self._tag.startswith("h") else "body"
                self.blocks.append((kind, unicodedata.normalize("NFC", text)))
        self._tag = None
        self._parts = []


def normalize_html(raw_html: bytes) -> NormalizedSource:
    """Extract ordered heading/body blocks from UTF-8 HTML."""

    try:
        decoded = raw_html.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("HTML source must be valid UTF-8") from exc
    parser = _BlockParser()
    parser.feed(decoded)
    parser.close()
    if not parser.blocks:
        raise ValueError("HTML source contains no supported text blocks")

    text_parts: list[str] = []
    sections: list[NormalizedSection] = []
    current_heading = "Document"
    for kind, block in parser.blocks:
        if kind == "heading":
            current_heading = block
        start = sum(len(part) for part in text_parts) + 2 * len(text_parts)
        text_parts.append(block)
        sections.append(NormalizedSection(current_heading, start, start + len(block)))
    return NormalizedSource("\n\n".join(text_parts), tuple(sections))


__all__ = [
    "NormalizedSection",
    "NormalizedSource",
    "normalize_html",
    "normalize_plain_text",
]
