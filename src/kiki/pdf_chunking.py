"""Page-aware PDF chunking that lets passages continue across page breaks.

Adapted from Zotero RAG `rag/chunking.py` (`chunk_document`, `_hard_split`),
https://github.com/rhenryliu/zotero-rag at commit
a9f308d27d6074c3a8c0478af23787ae4251acd1, Copyright (c) 2026 R. Henry Liu,
MIT License (full notice in THIRD_PARTY_NOTICES.md).

Kept from upstream: a document-order paragraph stream with each paragraph
tagged by its page, packing to a character budget, and sentence-boundary
splitting of oversized paragraphs.

Changed for Kiki:
* Overlap carries the previous chunk's last whole paragraph (Kiki's text-file
  policy) with its own page tags, so a chunk's page span covers all of its
  text. Upstream carries a character tail attributed to the new page.
* A sentence or paragraph interrupted by a page break is joined with its
  continuation before packing; each paragraph keeps a map from character
  offsets to pages, so split pieces report exactly the pages they contain.
* Repeated running headers/footers and bare page numbers are removed.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class Paragraph:
    text: str
    # (character offset, page number) for each page the text starts on, ascending.
    pages: tuple[tuple[int, int], ...]

    @property
    def start_page(self) -> int:
        return self.pages[0][1]

    @property
    def end_page(self) -> int:
        return self.pages[-1][1]

    def slice(self, start: int, end: int) -> Paragraph:
        """The text in [start, end), stripped, with the pages it actually covers."""
        raw = self.text[start:end]
        leading = len(raw) - len(raw.lstrip())
        text = raw.strip()
        start += leading
        end = start + len(text)
        covered = [
            (max(offset, start) - start, page)
            for index, (offset, page) in enumerate(self.pages)
            if offset < end
            and (index + 1 == len(self.pages) or self.pages[index + 1][0] > start)
        ]
        return Paragraph(text, tuple(covered))


@dataclass(frozen=True)
class PageChunk:
    start_page: int
    end_page: int
    text: str


_PAGE_NUMBER = re.compile(
    r"^\s*(?:page\s*)?[-–]?\s*\d{1,4}\s*[-–]?(?:\s*(?:of|/)\s*\d{1,4})?\s*$", re.I
)
_SENTENCE_END = re.compile(r"[.!?:;][\"'”’)\]]*$")
_SENTENCE_BREAK = re.compile(r"[.!?][\"'”’)\]]*\s+")


def strip_running_lines(pages: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Remove bare page numbers and headers/footers repeated across pages.

    A line counts as running text when it is among the first or last two
    non-empty lines of a page and, with digits normalized, appears in such a
    position on at least three pages and at least half of the pages with text.
    """

    def edges(lines: list[str]) -> list[int]:
        filled = [index for index, line in enumerate(lines) if line.strip()]
        return sorted(set(filled[:2] + filled[-2:]))

    def key(line: str) -> str:
        return re.sub(r"\d+", "#", re.sub(r"\s+", " ", line.strip().casefold()))

    split = [(number, text.splitlines()) for number, text in pages]
    counts: Counter[str] = Counter()
    for _, lines in split:
        counts.update({key(lines[index]) for index in edges(lines)})
    with_text = sum(1 for _, lines in split if any(line.strip() for line in lines))
    threshold = max(3, (with_text + 1) // 2)
    running = {line for line, count in counts.items() if count >= threshold}

    cleaned: list[tuple[int, str]] = []
    for number, lines in split:
        drop = {
            index
            for index in edges(lines)
            if key(lines[index]) in running or _PAGE_NUMBER.match(lines[index])
        }
        if all(index in drop for index, line in enumerate(lines) if line.strip()):
            # Never empty a page: on very short pages body lines can look repeated.
            drop = {index for index in drop if _PAGE_NUMBER.match(lines[index])}
        cleaned.append(
            (number, "\n".join(line for index, line in enumerate(lines) if index not in drop))
        )
    return cleaned


def page_paragraphs(pages: list[tuple[int, str]]) -> list[Paragraph]:
    """Document-order paragraphs, joining text interrupted by a page break."""
    stream: list[Paragraph] = []
    for number, text in pages:
        blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
        for position, block in enumerate(blocks):
            if position == 0 and stream and _continues(stream[-1].text, block):
                last = stream.pop()
                hyphenated = last.text.endswith("-") and block[:1].islower()
                body = last.text[:-1] if hyphenated else last.text + " "
                stream.append(Paragraph(body + block, (*last.pages, (len(body), number))))
            else:
                stream.append(Paragraph(block, ((0, number),)))
    return stream


def _continues(previous: str, following: str) -> bool:
    """True when `previous` stops mid-sentence and `following` picks it up."""
    tail = previous.rstrip()
    if tail.endswith("-") and following[:1].islower():
        return True
    if not tail or _SENTENCE_END.search(tail):
        return False
    # A capitalized opening after an unpunctuated line is more often a heading
    # or a new section than a continuation, so only lowercase and punctuation join.
    return following[:1].islower() or following[:1] in ",;:)]"


def hard_split(text: str, limit: int) -> list[tuple[int, int]]:
    """Character spans of at most `limit`, preferring sentence boundaries.

    Upstream `_hard_split`, returning spans instead of strings so page
    provenance can be computed for each piece.
    """
    spans: list[tuple[int, int]] = []
    start = 0
    while len(text) - start > limit:
        window = text[start : start + limit]
        cut = max((match.end() for match in _SENTENCE_BREAK.finditer(window)), default=0)
        if cut < limit // 3:
            space = window.rfind(" ")
            cut = space + 1 if space > limit // 3 else limit
        spans.append((start, start + cut))
        start += cut
    if text[start:].strip():
        spans.append((start, len(text)))
    return spans


def split_oversized(paragraphs: list[Paragraph], limit: int) -> list[Paragraph]:
    result: list[Paragraph] = []
    for paragraph in paragraphs:
        if len(paragraph.text) <= limit:
            result.append(paragraph)
            continue
        for start, end in hard_split(paragraph.text, limit):
            piece = paragraph.slice(start, end)
            if piece.text:
                result.append(piece)
    return result


def pack(paragraphs: list[Paragraph], limit: int) -> list[PageChunk]:
    """Pack paragraphs into chunks of about `limit` characters.

    Overlap matches Kiki's text policy: the previous chunk's last paragraph is
    carried forward when it fits, together with its own pages.
    """
    chunks: list[PageChunk] = []
    current: list[Paragraph] = []
    size = 0
    for paragraph in paragraphs:
        added = len(paragraph.text) + (2 if current else 0)
        if current and size + added > limit:
            chunks.append(_merge(current))
            overlap = current[-1]
            current = [overlap] if len(overlap.text) + len(paragraph.text) + 2 <= limit else []
            size = len(overlap.text) if current else 0
        current.append(paragraph)
        size += len(paragraph.text) + (2 if len(current) > 1 else 0)
    if current:
        chunks.append(_merge(current))
    return chunks


def chunk_pages(pages: list[tuple[int, str]], limit: int) -> list[PageChunk]:
    """Chunks with page spans from `(page_number, text)` pairs in document order."""
    paragraphs = page_paragraphs(strip_running_lines(pages))
    return pack(split_oversized(paragraphs, limit), limit)


def _merge(parts: list[Paragraph]) -> PageChunk:
    return PageChunk(
        min(part.start_page for part in parts),
        max(part.end_page for part in parts),
        "\n\n".join(part.text for part in parts),
    )
