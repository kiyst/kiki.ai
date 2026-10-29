from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from kiki import documents
from kiki.extraction import ExtractionError, document_title, extract_chunks
from kiki.finding import FileFinder
from kiki.retrieval import TextIndex

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _paragraph(text: str, style: str | None = None) -> str:
    properties = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    # Word splits text into runs; tabs and breaks sit between them.
    first, _, rest = text.partition(" ")
    return (f"<w:p>{properties}<w:r><w:t>{first}</w:t></w:r><w:r><w:tab/></w:r>"
            f"<w:r><w:t xml:space=\"preserve\">{rest}</w:t></w:r></w:p>")


def _docx(path: Path, paragraphs: list[str], *, title: str | None = None,
          styles: dict[int, str] | None = None) -> Path:
    styles = styles or {}
    body = "".join(_paragraph(text, styles.get(index)) for index, text in enumerate(paragraphs))
    table = f"<w:tbl><w:tr><w:tc>{_paragraph('Cell text inside a table')}</w:tc></w:tr></w:tbl>"
    deleted = "<w:p><w:del><w:r><w:delText>removed in tracked changes</w:delText></w:r></w:del></w:p>"
    xml = (f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{W}"><w:body>'
           f"{body}{table}{deleted}</w:body></w:document>")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", xml)
        if title is not None:
            archive.writestr("docProps/core.xml", (
                '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/'
                'metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/">'
                f"<dc:title>{title}</dc:title></cp:coreProperties>"))
    return path


def test_docx_paragraphs_tables_and_title(tmp_path: Path) -> None:
    path = _docx(tmp_path / "lease.docx",
                 ["Apartment Lease Agreement", "The security deposit is due on signing."],
                 styles={0: "Title"})

    title, paragraphs = documents.read_docx(path)

    assert title == "Apartment Lease Agreement"
    assert paragraphs == ["Apartment Lease Agreement", "The security deposit is due on signing.",
                          "Cell text inside a table"]
    assert all("removed" not in paragraph for paragraph in paragraphs)
    chunks = extract_chunks(path)
    assert [(c.location_kind, c.start_location, c.end_location) for c in chunks] == [("paragraph", 1, 3)]


def test_docx_title_property_wins_over_heading(tmp_path: Path) -> None:
    path = _docx(tmp_path / "x.docx", ["Some heading", "Body."], title="Q3 Board Memo",
                 styles={0: "Heading1"})
    assert document_title(path) == "Q3 Board Memo"
    untitled = _docx(tmp_path / "y.docx", ["Plain first line", "Body."])
    assert document_title(untitled) is None


@pytest.mark.parametrize("content", [b"\xd0\xcf\x11\xe0 old binary doc", b"PK\x03\x04 truncated"])
def test_unreadable_word_files_are_reported_not_raised(tmp_path: Path, content: bytes) -> None:
    path = tmp_path / "old.docx"
    path.write_bytes(content)
    with pytest.raises(ExtractionError, match="not a readable .docx"):
        extract_chunks(path)
    assert document_title(path) is None


def test_inflated_docx_body_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _docx(tmp_path / "big.docx", ["word " * 500])
    monkeypatch.setattr(documents, "MAX_DOCX_XML_BYTES", 1_000)
    with pytest.raises(ExtractionError, match="too large"):
        extract_chunks(path)


def test_html_text_title_and_skipped_code(tmp_path: Path) -> None:
    path = tmp_path / "recipe.html"
    path.write_text(
        "<html><head><title>Grandma's Pierogi</title><style>p{color:red}</style>"
        "<script>alert('never indexed')</script>"  # no </head>: body must survive
        "<body><h1>Pierogi</h1><p>Mix the <b>dough</b> &amp; rest it.</p>"
        "<ul><li>Potatoes</li><li>Farmer's cheese</li></ul><br>Boil gently.</body></html>",
        encoding="utf-8",
    )
    title, paragraphs = documents.read_html(path)
    assert title == "Grandma's Pierogi"
    assert paragraphs == ["Pierogi", "Mix the dough & rest it.", "Potatoes", "Farmer's cheese",
                          "Boil gently."]
    assert document_title(path) == "Grandma's Pierogi"
    assert extract_chunks(path)[0].location_kind == "paragraph"


def test_html_encodings_and_h1_fallback(tmp_path: Path) -> None:
    windows = tmp_path / "old.htm"
    windows.write_bytes("<h1>Café menu</h1><p>Crème brûlée</p>".encode("cp1252"))
    assert documents.read_html(windows) == ("Café menu", ["Café menu", "Crème brûlée"])
    declared = tmp_path / "latin.html"
    declared.write_bytes('<meta charset="iso-8859-1"><p>Señor</p>'.encode("latin-1"))
    assert documents.read_html(declared)[1] == ["Señor"]
    empty = tmp_path / "empty.html"
    empty.write_text("<script>only()</script>", encoding="utf-8")
    with pytest.raises(ExtractionError, match="no text"):
        extract_chunks(empty)


def test_word_and_html_are_searchable_cited_and_findable(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    root.mkdir()
    _docx(root / "Document1.docx", ["Kayak rental waiver", "Paddlers must wear a life vest."],
          styles={0: "Title"})
    (root / "saved-page.html").write_text("<title>Thermostat wiring</title><p>Red goes to R.</p>",
                                          encoding="utf-8")
    index = TextIndex(tmp_path / "index.sqlite3")
    counts = index.index_root(root)
    assert counts["indexed"] == 2 and counts["failed"] == 0

    result = index.search("life vest paddlers")[0]
    assert result.path.endswith("Document1.docx") and result.title == "Kayak rental waiver"
    assert "(paragraphs 1-3)" in result.citation  # the helper adds a table paragraph

    found = FileFinder(index).find("kayak waiver").candidates[0]
    assert found.name == "Document1.docx" and found.searchable
    assert found.reasons == {"title": ["kayak", "waiver"]}
    assert FileFinder(index).find("thermostat wiring").candidates[0].name == "saved-page.html"
