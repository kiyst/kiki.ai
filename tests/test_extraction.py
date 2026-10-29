from pathlib import Path

import pytest
from pypdf import PdfWriter

from deskai.extraction import ExtractionError, extract_chunks


def test_text_chunks_follow_paragraphs_and_keep_line_spans(tmp_path: Path) -> None:
    path = tmp_path / "history.txt"
    path.write_text(
        "Header\n\nWe the people.\nA short preamble.\n\n" + ("Long evidence sentence. " * 180),
        encoding="utf-8",
    )

    chunks = extract_chunks(path)

    assert chunks[0].start_location == 1
    assert "Header\n\nWe the people" in chunks[0].text
    assert all(len(chunk.text) < 5_000 for chunk in chunks)
    assert chunks[-1].end_location == 6


def test_image_only_or_blank_pdf_reports_ocr_limitation(tmp_path: Path) -> None:
    path = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with path.open("wb") as output:
        writer.write(output)

    with pytest.raises(ExtractionError, match="no extractable text"):
        extract_chunks(path)



def test_gutenberg_license_matter_is_not_indexed(tmp_path: Path) -> None:
    path = tmp_path / "book.txt"
    path.write_text(
        "The Project Gutenberg eBook of A Book\n\nLicense terms here.\n\n"
        "*** START OF THE PROJECT GUTENBERG EBOOK A BOOK ***\n\n"
        "We the People of the United States.\n\n"
        "*** END OF THE PROJECT GUTENBERG EBOOK A BOOK ***\n\n"
        "Full Project Gutenberg License.\n",
        encoding="utf-8",
    )

    chunks = extract_chunks(path)

    assert [chunk.text for chunk in chunks] == ["We the People of the United States."]
    assert (chunks[0].start_location, chunks[0].end_location) == (7, 7)


def test_document_title_reads_gutenberg_authors_and_markdown_heading(tmp_path: Path) -> None:
    from deskai.extraction import document_title

    book = tmp_path / "book.txt"
    book.write_text(
        "Title: The Federalist Papers\n\nAuthor: Alexander Hamilton\n        John Jay\n\nLanguage: English\n",
        encoding="utf-8",
    )
    notes = tmp_path / "notes.md"
    notes.write_text("Intro\n# Research notes\n", encoding="utf-8")
    plain = tmp_path / "plain.txt"
    plain.write_text("No header here.", encoding="utf-8")

    assert document_title(book) == "The Federalist Papers by Alexander Hamilton and John Jay"
    assert document_title(notes) == "Research notes"
    assert document_title(plain) is None
