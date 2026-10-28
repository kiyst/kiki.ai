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

