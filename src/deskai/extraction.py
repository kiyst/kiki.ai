from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".py", ".js", ".ts", ".tsx",
    ".jsx", ".json", ".toml", ".yaml", ".yml",
}
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | {".pdf"}
EXTRACTION_VERSION = "paragraph-v1"


@dataclass(frozen=True)
class ExtractedChunk:
    location_kind: str
    start_location: int
    end_location: int
    text: str


class ExtractionError(Exception):
    """A document could not be converted to searchable text."""


def extract_chunks(path: Path) -> list[ExtractedChunk]:
    if path.suffix.lower() == ".pdf":
        return list(_extract_pdf(path))
    return list(_extract_text(path))


def _extract_text(path: Path) -> Iterable[ExtractedChunk]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise ExtractionError("file is not valid UTF-8 text") from exc
    lines = text.splitlines()
    blocks = list(_paragraph_blocks(lines))
    max_characters = 2_800
    current: list[tuple[int, int, str]] = []
    current_size = 0
    for block in blocks:
        added_size = len(block[2]) + (2 if current else 0)
        if current and current_size + added_size > max_characters:
            yield _text_chunk(current)
            # Preserve one paragraph of context without repeatedly mixing
            # unrelated sections or front matter into short passages.
            overlap = current[-1]
            current = [overlap] if len(overlap[2]) + len(block[2]) + 2 <= max_characters else []
            current_size = len(overlap[2]) if current else 0
        current.append(block)
        current_size += len(block[2]) + (2 if len(current) > 1 else 0)
    if current:
        yield _text_chunk(current)


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


def _text_chunk(blocks: list[tuple[int, int, str]]) -> ExtractedChunk:
    return ExtractedChunk(
        "line",
        blocks[0][0],
        blocks[-1][1],
        "\n\n".join(block[2] for block in blocks),
    )


def _extract_pdf(path: Path) -> Iterable[ExtractedChunk]:
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError as exc:
        raise ExtractionError("PDF support is unavailable; install pypdf") from exc

    try:
        reader = PdfReader(path, strict=False)
        if reader.is_encrypted:
            raise ExtractionError("PDF is encrypted")
        found_text = False
        for page_number, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                found_text = True
                for passage in _bounded_passages(text):
                    yield ExtractedChunk("page", page_number, page_number, passage)
        if not found_text:
            raise ExtractionError("PDF has no extractable text; OCR is not enabled")
    except ExtractionError:
        raise
    except (PdfReadError, OSError, ValueError) as exc:
        raise ExtractionError(f"PDF could not be read: {type(exc).__name__}") from exc


def _bounded_passages(text: str, max_characters: int = 4_000, overlap: int = 400) -> Iterable[str]:
    if len(text) <= max_characters:
        yield text
        return
    step = max_characters - overlap
    for offset in range(0, len(text), step):
        passage = text[offset : offset + max_characters].strip()
        if passage:
            yield passage

