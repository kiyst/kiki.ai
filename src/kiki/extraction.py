from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .pdf_chunking import chunk_pages


TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".py", ".js", ".ts", ".tsx",
    ".jsx", ".json", ".toml", ".yaml", ".yml",
}
DOCX_EXTENSIONS = {".docx"}
HTML_EXTENSIONS = {".html", ".htm"}
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | DOCX_EXTENSIONS | HTML_EXTENSIONS | {".pdf"}
EXTRACTION_VERSION = "paragraph-v3"
# Versioned separately so a change to one format re-extracts only that format;
# other files keep their source IDs and embeddings.
PDF_EXTRACTION_VERSION = "pdf-continuous-v1"
DOCX_EXTRACTION_VERSION = "docx-v3"  # v2: hidden (w:vanish) text skipped; v3: w:val="0" is visible
HTML_EXTRACTION_VERSION = "html-v3"  # v2: hidden elements skipped
# Roughly what the RAG evidence budget shows the model per result, so retrieved
# chunks are seen whole and embeddings stay focused on one passage.
TEXT_CHUNK_CHARACTERS = 1_400


@dataclass(frozen=True)
class ExtractedChunk:
    location_kind: str
    start_location: int
    end_location: int
    text: str


class ExtractionError(Exception):
    """A document could not be converted to searchable text."""


def extraction_version(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return PDF_EXTRACTION_VERSION
    if suffix in DOCX_EXTENSIONS:
        return DOCX_EXTRACTION_VERSION
    if suffix in HTML_EXTENSIONS:
        return HTML_EXTRACTION_VERSION
    return EXTRACTION_VERSION


def extract_chunks(path: Path) -> list[ExtractedChunk]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return list(_extract_pdf(path))
    if suffix in DOCX_EXTENSIONS | HTML_EXTENSIONS:
        return list(_extract_document(path))
    return list(_extract_text(path))


def _read_document(path: Path) -> tuple[str | None, list[str]]:
    from .documents import DocumentError, read_docx, read_html

    try:
        return read_docx(path) if path.suffix.lower() in DOCX_EXTENSIONS else read_html(path)
    except DocumentError as exc:
        raise ExtractionError(str(exc)) from exc


def _extract_document(path: Path) -> Iterable[ExtractedChunk]:
    """Word and HTML passages cite paragraph numbers: one paragraph per line."""
    _, paragraphs = _read_document(path)
    if not paragraphs:
        raise ExtractionError("document has no text")
    return _chunk_lines(paragraphs, "paragraph")


def _extract_text(path: Path) -> Iterable[ExtractedChunk]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise ExtractionError("file is not valid UTF-8 text") from exc
    return _chunk_lines(_without_gutenberg_boilerplate(text.splitlines()), "line")


def _chunk_lines(lines: list[str], kind: str) -> Iterable[ExtractedChunk]:
    blocks = list(_paragraph_blocks(lines, min(2_400, TEXT_CHUNK_CHARACTERS)))
    max_characters = TEXT_CHUNK_CHARACTERS
    current: list[tuple[int, int, str]] = []
    current_size = 0
    for block in blocks:
        added_size = len(block[2]) + (2 if current else 0)
        if current and current_size + added_size > max_characters:
            yield _text_chunk(current, kind)
            # Preserve one paragraph of context without repeatedly mixing
            # unrelated sections or front matter into short passages.
            overlap = current[-1]
            current = [overlap] if len(overlap[2]) + len(block[2]) + 2 <= max_characters else []
            current_size = len(overlap[2]) if current else 0
        current.append(block)
        current_size += len(block[2]) + (2 if len(current) > 1 else 0)
    if current:
        yield _text_chunk(current, kind)


def document_title(path: Path) -> str | None:
    """Human title for citations: Gutenberg Title/Author, a Markdown H1, a Word
    document's title property or Title/Heading 1, or an HTML <title>/<h1>.

    Control characters are removed: titles are printed in /find and citations,
    and an ESC sequence in a heading reached the terminal (re-audit)."""
    title = _raw_document_title(path)
    if title is None:
        return None
    return re.sub("[\x00-\x1f\x7f-\x9f]", " ", title).strip() or None


def _raw_document_title(path: Path) -> str | None:
    if path.suffix.lower() in DOCX_EXTENSIONS | HTML_EXTENSIONS:
        try:
            return _read_document(path)[0]
        except (ExtractionError, OSError):
            return None
    if path.suffix.lower() not in TEXT_EXTENSIONS:
        return None
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            head = handle.read(4_000).splitlines()
    except OSError:
        return None
    title = _header_field(head, "Title")
    if title:
        authors = _header_field(head, "Author", separator=" and ")
        return f"{title} by {authors}" if authors else title
    if path.suffix.lower() in {".md", ".markdown"}:
        for line in head:
            if line.startswith("# "):
                return line[2:].strip() or None
    return None


def _header_field(lines: list[str], name: str, separator: str = " ") -> str | None:
    for index, line in enumerate(lines):
        if line.startswith(f"{name}:"):
            values = [line[len(name) + 1 :].strip()]
            # Gutenberg lists additional authors on indented continuation lines.
            for follower in lines[index + 1 :]:
                if not follower.startswith((" ", "\t")) or not follower.strip():
                    break
                values.append(follower.strip())
            return separator.join(value for value in values if value) or None
    return None


_GUTENBERG_START = re.compile(r"^\*{3}\s*START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK", re.I)
_GUTENBERG_END = re.compile(r"^\*{3}\s*END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK", re.I)


def _without_gutenberg_boilerplate(lines: list[str]) -> list[str]:
    """Blank Project Gutenberg license front/back matter, keeping line numbers.

    The license text is identical across books, so indexing it dilutes the
    embeddings of opening chunks and lets boilerplate outrank real evidence.
    """
    start = next((i for i, line in enumerate(lines) if _GUTENBERG_START.match(line)), None)
    if start is None:
        return lines
    end = next(
        (i for i in range(start + 1, len(lines)) if _GUTENBERG_END.match(lines[i])),
        len(lines),
    )
    return [line if start < i < end else "" for i, line in enumerate(lines)]


def _paragraph_blocks(lines: list[str], max_characters: int = 2_400) -> Iterable[tuple[int, int, str]]:
    """Return nonblank text blocks with their original one-based line spans."""
    start: int | None = None
    selected: list[str] = []
    for line_number, line in enumerate([*lines, ""], start=1):
        if line.strip():
            if start is None:
                start = line_number
            selected.append(line)
            continue
        if start is None:
            continue
        offset = 0
        while offset < len(selected):
            if len(selected[offset]) > max_characters:
                line_number = start + offset
                for character in range(0, len(selected[offset]), max_characters):
                    yield (
                        line_number,
                        line_number,
                        selected[offset][character : character + max_characters],
                    )
                offset += 1
                continue
            end = offset
            size = 0
            while end < len(selected) and (
                size + len(selected[end]) + 1 <= max_characters or end == offset
            ):
                size += len(selected[end]) + 1
                end += 1
            yield start + offset, start + end - 1, "\n".join(selected[offset:end])
            offset = end
        start = None
        selected = []


def _text_chunk(blocks: list[tuple[int, int, str]], kind: str = "line") -> ExtractedChunk:
    return ExtractedChunk(
        kind,
        blocks[0][0],
        blocks[-1][1],
        "\n\n".join(block[2] for block in blocks),
    )


def _extract_pdf(path: Path) -> Iterable[ExtractedChunk]:
    """Passages that may continue across page breaks, with start and end pages.

    Blank and image-only pages contribute nothing; a page whose text cannot be
    extracted is skipped so the rest of a partly damaged PDF stays searchable.
    """
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError as exc:
        raise ExtractionError("PDF support is unavailable; install pypdf") from exc

    try:
        reader = PdfReader(path, strict=False)
        if reader.is_encrypted:
            raise ExtractionError("PDF is encrypted")
        pages: list[tuple[int, str]] = []
        for page_number, page in enumerate(reader.pages, start=1):
            try:
                text = (page.extract_text() or "").strip()
            except Exception:  # noqa: BLE001 - pypdf raises many types on damaged pages
                continue
            if text:
                pages.append((page_number, text))
    except ExtractionError:
        raise
    except (PdfReadError, OSError, ValueError) as exc:
        raise ExtractionError(f"PDF could not be read: {type(exc).__name__}") from exc
    if not pages:
        raise ExtractionError("PDF has no extractable text; OCR is not enabled")
    for chunk in chunk_pages(pages, TEXT_CHUNK_CHARACTERS):
        yield ExtractedChunk("page", chunk.start_page, chunk.end_page, chunk.text)
