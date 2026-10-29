"""Word (.docx) and web page (.html) text, using only the standard library.

Both return a title (or None) and the document's paragraphs in reading order,
so passages can cite "paragraphs 12-18". Nothing is executed or fetched: Word
macros are never read, HTML scripts and styles are dropped, and links,
images, and external entities are ignored.
"""
from __future__ import annotations

import re
import zipfile
import zlib
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

# A .docx is a zip; refuse an inflated body this large rather than unpack it.
MAX_DOCX_XML_BYTES = 64 * 1024 * 1024

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_DC_TITLE = "{http://purl.org/dc/elements/1.1/}title"


class DocumentError(Exception):
    """The file is not a document Kiki can read."""


def read_docx(path: Path) -> tuple[str | None, list[str]]:
    try:
        with zipfile.ZipFile(path) as archive:
            body = _read_member(archive, "word/document.xml")
            try:
                core = _read_member(archive, "docProps/core.xml")
            except KeyError:
                core = None
    except KeyError as exc:
        raise DocumentError("not a Word document (no document body)") from exc
    except (zipfile.BadZipFile, OSError, EOFError, RuntimeError, NotImplementedError,
            zlib.error) as exc:
        # Old binary .doc files and password-protected .docx files are not zips.
        raise DocumentError("not a readable .docx (old .doc format or password-protected?)") from exc
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        raise DocumentError("Word document is damaged") from exc

    paragraphs: list[str] = []
    heading: str | None = None
    for paragraph in root.iter(f"{_W}p"):
        text = _docx_paragraph_text(paragraph)
        if not text:
            continue
        paragraphs.append(text)
        style = paragraph.find(f"{_W}pPr/{_W}pStyle")
        name = (style.get(f"{_W}val") or "").casefold() if style is not None else ""
        if heading is None and name in {"title", "heading1"}:
            heading = text
    return _docx_title(core) or heading, paragraphs


def _read_member(archive: zipfile.ZipFile, name: str) -> bytes:
    info = archive.getinfo(name)
    if info.file_size > MAX_DOCX_XML_BYTES:
        raise DocumentError("Word document body is too large to read")
    return archive.read(info)


def _docx_paragraph_text(paragraph: ElementTree.Element) -> str:
    parts: list[str] = []
    for node in paragraph.iter():
        if node.tag == f"{_W}t" and node.text:
            parts.append(node.text)
        elif node.tag in {f"{_W}tab", f"{_W}br", f"{_W}cr"}:
            parts.append(" ")
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def _docx_title(core: bytes | None) -> str | None:
    if not core:
        return None
    try:
        element = ElementTree.fromstring(core).find(_DC_TITLE)
    except ElementTree.ParseError:
        return None
    title = (element.text or "").strip() if element is not None else ""
    return title or None


_BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "br", "caption", "dd", "div", "dl", "dt",
    "figcaption", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr",
    "li", "main", "nav", "ol", "p", "pre", "section", "table", "td", "th", "tr", "ul",
}
# Not "head": a page missing </head> would lose its whole body. The title is
# captured separately and head scripts and styles are skipped anyway.
_SKIPPED_TAGS = {"script", "style", "noscript", "template", "svg"}


class _TextCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.paragraphs: list[str] = []
        self.title_parts: list[str] = []
        self.first_h1: str | None = None
        self._current: list[str] = []
        self._skipping: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
        elif tag in _SKIPPED_TAGS:
            self._skipping.append(tag)
        elif tag in _BLOCK_TAGS:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif self._skipping and tag == self._skipping[-1]:
            self._skipping.pop()
        elif tag in _BLOCK_TAGS:
            text = self._flush()
            if tag == "h1" and text and self.first_h1 is None:
                self.first_h1 = text

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        elif not self._skipping:
            self._current.append(data)

    def close(self) -> None:
        super().close()
        self._flush()

    def _flush(self) -> str:
        text = re.sub(r"\s+", " ", "".join(self._current)).strip()
        self._current = []
        if text:
            self.paragraphs.append(text)
        return text


def read_html(path: Path) -> tuple[str | None, list[str]]:
    collector = _TextCollector()
    collector.feed(_decode_html(path.read_bytes()))
    collector.close()
    title = re.sub(r"\s+", " ", "".join(collector.title_parts)).strip()
    return title or collector.first_h1, collector.paragraphs


def _decode_html(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    declared = re.search(rb"""<meta[^>]+charset=["']?([\w-]+)""", data[:4096], re.I)
    if declared:
        try:
            return data.decode(declared.group(1).decode("ascii"), errors="replace")
        except LookupError:
            pass
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        # Pages saved by older Windows tools are usually Windows-1252.
        return data.decode("cp1252", errors="replace")
