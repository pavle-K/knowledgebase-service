"""Chunk markdown by heading, then by paragraph within each section.

Paragraph granularity matters for secret scanning: a heuristic false positive
drops its whole chunk (see src/ingestion/secrets.py), so smaller chunks limit
collateral loss to one paragraph instead of an entire section.
"""

from __future__ import annotations

import re

MAX_CONTENT_BYTES = 200_000
_HEADING_RE = re.compile(r"^#{1,2}\s+.*$", re.MULTILINE)
_HEADING_LINE_RE = re.compile(r"^#{1,2}\s+")
_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n")


def _split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in _PARAGRAPH_SPLIT_RE.split(text) if p.strip()]


def _split_section(section: str) -> list[str]:
    first_line, _, rest = section.partition("\n")
    if not _HEADING_LINE_RE.match(first_line):
        return _split_paragraphs(section)

    paragraphs = _split_paragraphs(rest)
    if not paragraphs:
        return [first_line]
    return [f"{first_line}\n{paragraph}" for paragraph in paragraphs]


def chunk_markdown(content: str) -> list[str]:
    if len(content.encode("utf-8")) > MAX_CONTENT_BYTES:
        return []

    content = content.strip()
    if not content:
        return []

    boundaries = [m.start() for m in _HEADING_RE.finditer(content)]
    if not boundaries or boundaries[0] != 0:
        boundaries = [0, *boundaries]

    ends = [*boundaries[1:], len(content)]
    sections = [
        section
        for start, end in zip(boundaries, ends, strict=True)
        if (section := content[start:end].strip())
    ]

    return [chunk for section in sections for chunk in _split_section(section)]
