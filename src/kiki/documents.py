"""Word (.docx) and web page (.html) text, using only the standard library.

Both return a title (or None) and the document's paragraphs in reading order,
so passages can cite "paragraphs 12-18". Nothing is executed or fetched: Word
macros are never read, HTML scripts and styles are dropped, and links,
images, and external entities are ignored.
"""
from __future__ import annotations

import codecs
import re
import zipfile
import zlib
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

# A .docx is a zip; refuse an inflated body this large rather than unpack it.
MAX_DOCX_XML_BYTES = 64 * 1024 * 1024
# A 500-page report has a few hundred thousand XML elements.
MAX_DOCX_ELEMENTS = 2_000_000

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
    # A huge element count is a crafted file, not a document (audit A6).
    if sum(1 for _ in zip(root.iter(), range(MAX_DOCX_ELEMENTS + 1))) > MAX_DOCX_ELEMENTS:
        raise DocumentError("Word document has too many parts to read")
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
    """The paragraph's own text, in order, without paragraphs nested inside it
    (they are read separately) and without hidden text (w:vanish).

    One pass over the paragraph's own nodes: walking every descendant of every
    paragraph made deliberately nested paragraphs cost the square of their
    depth, so a 5 KB file stalled indexing (audit A6)."""
    parts: list[str] = []
    stack = list(reversed(list(paragraph)))
    while stack:
        node = stack.pop()
        if node.tag == f"{_W}p":
            continue
        if node.tag == f"{_W}r" and node.find(f"{_W}rPr/{_W}vanish") is not None:
            continue  # hidden text: not visible in Word, so not read (audit L2)
        if node.tag == f"{_W}t" and node.text:
            parts.append(node.text)
        elif node.tag in {f"{_W}tab", f"{_W}br", f"{_W}cr"}:
            parts.append(" ")
        stack.extend(reversed(list(node)))
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
# A marked main region shorter than this is probably a stub, not the content.
MIN_MAIN_CHARACTERS = 500
# Elements with no closing tag; one marked hidden must not hide the rest of the page.
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
              "param", "source", "track", "wbr"}
_HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.IGNORECASE)


def _is_hidden(attrs: list[tuple[str, str | None]]) -> bool:
    values = {name.casefold(): (value or "") for name, value in attrs}
    return ("hidden" in values
            or values.get("aria-hidden", "").casefold() == "true"
            or bool(_HIDDEN_STYLE.search(values.get("style", ""))))


class _TextCollector(HTMLParser):
    def __init__(self, *, skip_hidden: bool = False) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_hidden = skip_hidden
        self._hidden_tag: str | None = None
        self._hidden_depth = 0
        self.paragraphs: list[str] = []
        self.title_parts: list[str] = []
        self.first_h1: str | None = None
        # Indexes into `paragraphs` of top-level section headings (<h2>).
        self.section_starts: list[int] = []
        # Indexes of paragraphs inside the page's marked main content
        # (<main>, role="main", or <article>), outside menus and sidebars.
        self.in_main: set[int] = set()
        self._current: list[str] = []
        self._skipping: list[str] = []
        self._in_title = False
        self._main_tag: str | None = None
        self._main_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._hidden_tag is not None:
            if tag == self._hidden_tag:
                self._hidden_depth += 1
            return
        if self._skip_hidden and tag not in _VOID_TAGS and _is_hidden(attrs):
            # Text a visitor never sees, a common place to hide instructions
            # meant for AI readers. Nested tags of the same name are counted
            # so the whole element is skipped.
            self._hidden_tag, self._hidden_depth = tag, 1
            return
        if self._main_tag == tag:
            self._main_depth += 1
        elif self._main_tag is None and (
            tag in {"main", "article"} or dict(attrs).get("role") == "main"
        ):
            self._flush()
            self._main_tag, self._main_depth = tag, 1
        if tag == "title" and not self._skipping:
            # Not inside <svg>, whose icons carry their own <title> labels.
            self._in_title = True
        elif tag in _SKIPPED_TAGS:
            self._skipping.append(tag)
        elif tag in _BLOCK_TAGS:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if self._hidden_tag is not None:
            if tag == self._hidden_tag:
                self._hidden_depth -= 1
                if self._hidden_depth == 0:
                    self._hidden_tag = None
            return
        if tag == "title":
            self._in_title = False
        elif self._skipping and tag == self._skipping[-1]:
            self._skipping.pop()
        elif tag in _BLOCK_TAGS:
            text = self._flush()
            if tag == "h1" and text and self.first_h1 is None:
                self.first_h1 = text
            elif tag == "h2" and text:
                self.section_starts.append(len(self.paragraphs) - 1)
        if self._main_tag == tag:
            self._main_depth -= 1
            if self._main_depth == 0:
                self._flush()
                self._main_tag = None

    def handle_data(self, data: str) -> None:
        if self._hidden_tag is not None:
            return
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
            if self._main_tag is not None:
                self.in_main.add(len(self.paragraphs))
            self.paragraphs.append(text)
        return text


def read_html(path: Path) -> tuple[str | None, list[str]]:
    return html_text(path.read_bytes())


def html_text(data: bytes, encoding: str | None = None) -> tuple[str | None, list[str]]:
    """Title and paragraphs of an HTML page; `encoding` is a server-declared charset."""
    title, paragraphs, _ = html_document(data, encoding)
    return title, paragraphs


def html_document(
    data: bytes, encoding: str | None = None, *, main_only: bool = False,
    skip_hidden: bool = False,
) -> tuple[str | None, list[str], list[int]]:
    """Title, paragraphs, and the indexes of paragraphs that are section headings.

    With `main_only`, a page that marks its main content (and has a real amount
    of text there) is read without its menus, sidebars, and footers. With
    `skip_hidden`, elements a visitor can't see are left out."""
    text = None
    encoding = safe_charset(encoding)
    if encoding:
        text = data.decode(encoding, errors="replace")
    collector = _TextCollector(skip_hidden=skip_hidden)
    collector.feed(text if text is not None else _decode_html(data))
    collector.close()
    title = re.sub(r"\s+", " ", "".join(collector.title_parts)).strip()
    paragraphs, sections = collector.paragraphs, collector.section_starts
    main = sorted(collector.in_main)
    if main_only and sum(len(paragraphs[index]) for index in main) >= MIN_MAIN_CHARACTERS:
        renumber = {old: new for new, old in enumerate(main)}
        paragraphs = [paragraphs[index] for index in main]
        sections = [renumber[index] for index in sections if index in renumber]
    return title or collector.first_h1, paragraphs, sections


# Text encodings real pages use. Any other declared name is ignored: Python
# also ships codecs like "punycode" whose decoding is super-quadratic, so a
# page declaring one could stall Kiki for minutes (audit A11).
_SAFE_CHARSETS = frozenset({
    "utf-8", "utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "utf-32", "utf-32-le", "utf-32-be",
    "ascii", "latin-1", "cp437", "cp850", "cp866", "mac-roman", "koi8-r", "koi8-u",
    *(f"iso8859-{number}" for number in range(1, 17)),
    *(f"cp{number}" for number in range(1250, 1259)),
    "shift_jis", "cp932", "euc_jp", "iso2022_jp", "gb2312", "gbk", "gb18030", "cp936",
    "big5", "big5hkscs", "cp950", "euc_kr", "cp949", "iso2022_kr", "tis-620", "cp874",
})


def safe_charset(name: str | None) -> str | None:
    """The codec for a declared charset if it is one real pages use, else None."""
    if not name:
        return None
    try:
        codec = codecs.lookup(name.strip()).name
    except (LookupError, ValueError):
        return None
    return codec if codec in _SAFE_CHARSETS else None


def _decode_html(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    declared = re.search(rb"""<meta[^>]+charset=["']?([\w-]+)""", data[:4096], re.I)
    encoding = safe_charset(declared.group(1).decode("ascii")) if declared else None
    if encoding:
        return data.decode(encoding, errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        # Pages saved by older Windows tools are usually Windows-1252.
        return data.decode("cp1252", errors="replace")
