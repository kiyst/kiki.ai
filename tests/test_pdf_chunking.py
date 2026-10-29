"""PDF passages that cross page boundaries without losing page provenance."""

from pathlib import Path

import pytest

from kiki.extraction import (
    EXTRACTION_VERSION,
    PDF_EXTRACTION_VERSION,
    TEXT_CHUNK_CHARACTERS,
    ExtractionError,
    extract_chunks,
    extraction_version,
)
from kiki.pdf_chunking import Paragraph, chunk_pages, hard_split, page_paragraphs, strip_running_lines
from kiki.retrieval import TextIndex


def make_pdf(pages: list[list[str] | None], *, image_only: set[int] = frozenset()) -> bytes:
    """Minimal valid PDF: each page draws its lines with Helvetica, top to bottom.

    `None` makes a blank page; pages in `image_only` contain only an image
    XObject, like a scanned page without OCR.
    """
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    image = add(
        b"<< /Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceGray "
        b"/BitsPerComponent 8 /Length 1 >>\nstream\n\x80\nendstream"
    )
    page_ids: list[int] = []
    pages_id = len(objects) + 2 * len(pages) + 1
    for number, lines in enumerate(pages, start=1):
        if number in image_only:
            content = b"q 100 0 0 100 50 50 cm /Im1 Do Q"
        else:
            parts = [b"BT /F1 11 Tf 14 TL 50 760 Td"]
            for line in lines or []:
                escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
                parts.append(b"(" + escaped.encode("latin-1") + b") Tj T*")
            parts.append(b"ET")
            content = b"\n".join(parts) if lines else b""
        stream = add(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
        page_ids.append(
            add(
                b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 612 792] /Contents %d 0 R "
                b"/Resources << /Font << /F1 %d 0 R >> /XObject << /Im1 %d 0 R >> >> >>"
                % (pages_id, stream, font, image)
            )
        )
    kids = b" ".join(b"%d 0 R" % page for page in page_ids)
    assert add(b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, len(page_ids))) == pages_id
    catalog = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id)
    output = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(output)
    output += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    output += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    output += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        catalog,
        xref,
    )
    return bytes(output)


def write_pdf(tmp_path: Path, name: str, pages: list[list[str] | None], **kwargs) -> Path:
    path = tmp_path / name
    path.write_bytes(make_pdf(pages, **kwargs))
    return path


def chunk_containing(chunks, phrase):
    matches = [chunk for chunk in chunks if phrase in " ".join(chunk.text.split())]
    assert matches, f"{phrase!r} not found in any chunk"
    return matches[0]


def test_sentence_divided_across_two_pages_stays_in_one_passage(tmp_path: Path) -> None:
    path = write_pdf(
        tmp_path,
        "sentence.pdf",
        [
            ["The treaty was signed in Paris and the delegates agreed that the"],
            ["boundary would follow the river to its source."],
        ],
    )

    chunks = extract_chunks(path)

    chunk = chunk_containing(chunks, "agreed that the boundary would follow the river")
    assert (chunk.location_kind, chunk.start_location, chunk.end_location) == ("page", 1, 2)


def test_paragraph_divided_across_pages_keeps_both_page_numbers() -> None:
    pages = [
        (4, "Opening paragraph ends here.\n\nThe second paragraph begins on this page and"),
        (5, "continues on the next one, finishing here.\n\nA new paragraph on page five."),
    ]

    chunks = chunk_pages(pages, 200)

    joined = chunk_containing(chunks, "begins on this page and continues on the next one")
    assert (joined.start_page, joined.end_page) == (4, 5)
    assert (chunk_containing(chunks, "A new paragraph").end_page) == 5
    assert chunk_containing(chunks, "Opening paragraph").start_page == 4


def test_hyphenated_word_split_across_pages_is_rejoined() -> None:
    paragraphs = page_paragraphs([(1, "The consti-"), (2, "tution was ratified.")])

    assert [paragraph.text for paragraph in paragraphs] == ["The constitution was ratified."]
    assert (paragraphs[0].start_page, paragraphs[0].end_page) == (1, 2)


def test_capitalized_heading_after_unpunctuated_line_is_not_joined() -> None:
    paragraphs = page_paragraphs([(1, "Chapter One"), (2, "Article II describes the executive.")])

    assert len(paragraphs) == 2


def test_repeated_headers_footers_and_page_numbers_are_removed(tmp_path: Path) -> None:
    bodies = ["Rivers shaped early trade.", "Canals followed the rivers.", "Railways replaced canals.", "Highways came last."]
    pages = [
        ["JOURNAL OF EXAMPLE STUDIES", body, f"Unique detail about topic {n}.", f"Page {n} of 4"]
        for n, body in enumerate(bodies, start=1)
    ]
    path = write_pdf(tmp_path, "headers.pdf", pages)

    chunks = extract_chunks(path)

    text = " ".join(chunk.text for chunk in chunks)
    assert "JOURNAL OF EXAMPLE STUDIES" not in text
    assert "Page 2 of 4" not in text
    for body in bodies:
        assert body in text


def test_short_documents_keep_lines_that_only_look_repeated() -> None:
    cleaned = strip_running_lines([(1, "Summary\nFirst point."), (2, "Summary\nSecond point.")])

    assert all(text.startswith("Summary") for _, text in cleaned)


def test_blank_and_image_only_pages_are_skipped_with_correct_numbering(tmp_path: Path) -> None:
    path = write_pdf(
        tmp_path,
        "mixed.pdf",
        [["Introduction text on page one."], None, ["Scanned"], ["Conclusion text on page four."]],
        image_only={3},
    )

    chunks = extract_chunks(path)

    assert chunk_containing(chunks, "Introduction text").start_location == 1
    conclusion = chunk_containing(chunks, "Conclusion text")
    assert conclusion.end_location == 4
    assert all(chunk.start_location != 3 or "Introduction" in chunk.text for chunk in chunks)


def test_image_only_pdf_reports_ocr_limitation(tmp_path: Path) -> None:
    path = write_pdf(tmp_path, "scan.pdf", [["x"], ["y"]], image_only={1, 2})

    with pytest.raises(ExtractionError, match="no extractable text"):
        extract_chunks(path)


def test_malformed_pdf_fails_with_a_clear_error(tmp_path: Path) -> None:
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 9 0 R")

    with pytest.raises(ExtractionError):
        extract_chunks(path)


def test_partially_readable_pdf_keeps_readable_pages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = write_pdf(tmp_path, "partial.pdf", [["Readable first page."], ["Damaged page."], ["Readable third page."]])
    from pypdf import PageObject

    original = PageObject.extract_text

    def flaky(self, *args, **kwargs):
        text = original(self, *args, **kwargs)
        if "Damaged" in text:
            raise ValueError("corrupt content stream")
        return text

    monkeypatch.setattr(PageObject, "extract_text", flaky)

    chunks = extract_chunks(path)

    text = " ".join(chunk.text for chunk in chunks)
    assert "Readable first page." in text and "Readable third page." in text
    assert "Damaged" not in text


def test_long_pdf_passages_respect_the_text_chunk_budget_and_page_order(tmp_path: Path) -> None:
    sentence = "Evidence sentence number {n} describes a separate fact in detail."
    pages = [[sentence.format(n=page * 100 + line) for line in range(30)] for page in range(1, 5)]
    path = write_pdf(tmp_path, "long.pdf", pages)

    chunks = extract_chunks(path)

    assert len(chunks) > 4
    assert all(len(chunk.text) <= TEXT_CHUNK_CHARACTERS for chunk in chunks)
    assert all(chunk.start_location <= chunk.end_location for chunk in chunks)
    assert [chunk.start_location for chunk in chunks] == sorted(chunk.start_location for chunk in chunks)
    for chunk in chunks:
        numbers = [int(word) for word in chunk.text.replace(".", " ").split() if word.isdigit()]
        pages_in_text = {number // 100 for number in numbers}
        assert min(pages_in_text) >= chunk.start_location
        assert max(pages_in_text) <= chunk.end_location


def test_split_pieces_report_only_the_pages_they_contain() -> None:
    paragraph = Paragraph("a" * 50 + ". " + "b" * 50 + ".", ((0, 7), (52, 8)))

    pieces = [paragraph.slice(start, end) for start, end in hard_split(paragraph.text, 60)]

    assert [(piece.start_page, piece.end_page) for piece in pieces] == [(7, 7), (8, 8)]


def test_pdf_extraction_is_versioned_separately_from_text() -> None:
    assert extraction_version(Path("a.pdf")) == PDF_EXTRACTION_VERSION
    assert extraction_version(Path("a.txt")) == EXTRACTION_VERSION == "paragraph-v3"


def test_indexed_pdf_passages_carry_page_spans(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "notes.txt").write_text("Plain notes about rivers.", encoding="utf-8")
    (corpus / "report.pdf").write_bytes(
        make_pdf([["The river crossing was planned for the"], ["first week of spring."]])
    )
    index = TextIndex(tmp_path / "index.sqlite3")
    index.index_root(corpus)

    pdf_hit = index.search("river crossing spring", 5)[0]
    assert (pdf_hit.location_kind, pdf_hit.start_location, pdf_hit.end_location) == ("page", 1, 2)
    assert "pages 1-2" in pdf_hit.citation or "p.1-2" in pdf_hit.citation
