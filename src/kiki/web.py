"""Read one web page the user links with /web, and pick the passages that fit.

Kiki goes online only when the user types /web (or asks for weather), and
never when KIKI_OFFLINE is set. Only public http(s) addresses are fetched:
every redirect hop is re-checked, so a page cannot bounce Kiki onto the
user's own computer or local network. Downloads are capped, nothing on the
page is executed, and every request is appended to a log the user can read.

A page is usually far longer than a 4K-context model can hold, so the page
is cut into passages and only the ones that best match the question are
shown to the model, within the same evidence budget document answers use.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import os
import re
import socket
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlsplit

import httpx

from .documents import html_text
from .retrieval import SearchResult

MAX_PAGE_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 5
TIMEOUT_SECONDS = 15.0
# Passages are built from whole paragraphs up to about this many characters.
PASSAGE_CHARACTERS = 1_200
USER_AGENT = "Kiki/0.1 (personal assistant; reads pages its user links; +https://github.com/kiyst/kiki.ai)"

_HTML_TYPES = {"text/html", "application/xhtml+xml"}
_TEXT_TYPES = {"text/plain", "text/markdown", "text/x-markdown", "application/vnd.github.raw",
               "application/json", "text/csv"}

Resolver = Callable[[str, int], list[str]]


class WebError(ValueError):
    """A page Kiki will not or cannot read; the message is meant for the user."""


def offline_mode() -> bool:
    return os.getenv("KIKI_OFFLINE", "").strip().casefold() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class WebPage:
    url: str
    fetched_from: str
    title: str
    # (location number, text): paragraph numbers for web pages, line numbers for text files.
    blocks: list[tuple[int, str]]
    location_kind: str
    size: int
    truncated: bool = False
    note: str | None = None
    fetched_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))

    @property
    def host(self) -> str:
        return urlsplit(self.url).hostname or self.url

    @property
    def words(self) -> int:
        return sum(len(text.split()) for _, text in self.blocks)

    @property
    def source_id(self) -> str:
        digest = hashlib.sha256(self.url.encode())
        for number, text in self.blocks:
            digest.update(f"\0{number}\0{text}".encode())
        return f"web-{digest.hexdigest()[:12]}"


def looks_like_url(text: str) -> bool:
    # A bare address needs a letter top-level domain, so "python3.14" is a word, not a site.
    return bool(re.match(r"^(https?://\S+|([\w-]+\.)+[a-z]{2,}(:\d+)?([/?#]\S*)?)$", text, re.I))


def normalize_url(text: str) -> str:
    text = text.strip().strip("<>")
    if not re.match(r"^[a-z][a-z0-9+.-]*://", text, re.I):
        text = "https://" + text
    parts = urlsplit(text)
    if parts.scheme.casefold() not in {"http", "https"}:
        raise WebError("Kiki only reads http:// and https:// addresses.")
    if not parts.hostname:
        raise WebError(f"That doesn't look like a web address: {text}")
    if parts.username or parts.password:
        raise WebError("Addresses with a username or password in them aren't supported.")
    return text


def reading_address(url: str) -> tuple[str, dict[str, str], str | None]:
    """Where to fetch `url` from, extra headers, and a note for the user.

    Wikipedia articles and GitHub files have cleaner versions than the page a
    browser shows: the article body without menus, and the raw file or README
    without GitHub's page around it.
    """
    parts = urlsplit(url)
    host = (parts.hostname or "").casefold()
    path = parts.path
    wiki = re.fullmatch(r"([a-z-]+)(?:\.m)?\.wikipedia\.org", host)
    if wiki and path.startswith("/wiki/") and len(path) > 6:
        title = path[6:]
        return (
            f"https://{wiki.group(1)}.wikipedia.org/w/index.php?title={title}&action=render",
            {},
            "Reading the article text only (no menus or sidebars).",
        )
    if host in {"github.com", "www.github.com"}:
        segments = [unquote(item) for item in path.strip("/").split("/") if item]
        if len(segments) == 2 or (len(segments) >= 3 and segments[2] == "tree" and len(segments) <= 4):
            owner, repo = segments[:2]
            ref = f"?ref={quote(segments[3])}" if len(segments) == 4 else ""
            return (
                f"https://api.github.com/repos/{quote(owner)}/{quote(repo)}/readme{ref}",
                {"Accept": "application/vnd.github.raw"},
                "Reading the repository's README.",
            )
        if len(segments) >= 5 and segments[2] == "blob":
            owner, repo, _, *rest = segments
            return (
                "https://raw.githubusercontent.com/" + "/".join(quote(item) for item in [owner, repo, *rest]),
                {},
                "Reading the raw file.",
            )
    return url, {}, None


def resolve_host(host: str, port: int) -> list[str]:
    try:
        return sorted({item[4][0] for item in socket.getaddrinfo(host, port)})
    except socket.gaierror as exc:
        raise WebError(f"Couldn't find {host}. Check the address and your internet connection.") from exc


def _check_public(url: str, resolver: Resolver) -> None:
    parts = urlsplit(url)
    host = parts.hostname or ""
    port = parts.port or (443 if parts.scheme == "https" else 80)
    for address in resolver(host, port):
        ip = ipaddress.ip_address(address.split("%", 1)[0])
        if not ip.is_global:
            raise WebError(
                f"{host} points to your own computer or local network ({ip}). "
                "Kiki only reads public web pages."
            )


def fetch_page(
    url: str,
    *,
    client: httpx.Client | None = None,
    resolver: Resolver = resolve_host,
    log: Path | None = None,
) -> WebPage:
    """Download and read one page. Raises WebError with a message for the user."""
    if offline_mode():
        raise WebError("Kiki is in offline mode (KIKI_OFFLINE is set), so she won't go online.")
    requested = normalize_url(url)
    target, headers, note = reading_address(requested)
    owned = client is None
    client = client or httpx.Client(timeout=TIMEOUT_SECONDS)
    record: dict[str, object] = {"time": datetime.now(UTC).isoformat(timespec="seconds"),
                                 "requested": requested}
    try:
        page = _download(client, requested, target, headers, note, resolver, record)
        record.update(status="ok", bytes=page.size)
        return page
    except WebError as exc:
        record.update(status="refused or failed", reason=str(exc))
        raise
    except httpx.TimeoutException as exc:
        record.update(status="timeout")
        raise WebError(f"{urlsplit(target).hostname} took too long to answer.") from exc
    except httpx.HTTPError as exc:
        record.update(status="network error", reason=type(exc).__name__)
        raise WebError(f"Couldn't reach {urlsplit(target).hostname}: {type(exc).__name__}.") from exc
    finally:
        if owned:
            client.close()
        if log is not None:
            _append_log(log, record)


def _download(
    client: httpx.Client,
    requested: str,
    target: str,
    headers: dict[str, str],
    note: str | None,
    resolver: Resolver,
    record: dict[str, object],
) -> WebPage:
    hops: list[str] = []
    current = target
    for _ in range(MAX_REDIRECTS + 1):
        _check_public(current, resolver)
        hops.append(current)
        with client.stream(
            "GET", current, headers={"User-Agent": USER_AGENT, **headers}, follow_redirects=False
        ) as response:
            if response.is_redirect and response.headers.get("location"):
                current = normalize_url(urljoin(current, response.headers["location"]))
                continue
            record["fetched"] = hops
            record["http_status"] = response.status_code
            if response.status_code == 404:
                raise WebError(f"That page doesn't exist (404): {requested}")
            if response.status_code in {401, 403}:
                raise WebError(f"{urlsplit(current).hostname} refused the request "
                               f"({response.status_code}); it may need a login or block automated readers.")
            if response.status_code == 429:
                raise WebError(f"{urlsplit(current).hostname} says too many requests; try again later.")
            if response.status_code >= 400:
                raise WebError(f"{urlsplit(current).hostname} answered with an error ({response.status_code}).")
            media = response.headers.get("content-type", "").split(";", 1)[0].strip().casefold()
            charset = response.charset_encoding
            if media == "application/pdf":
                raise WebError("That link is a PDF. Kiki can't read PDFs from the web yet; "
                               "download it and add its folder with /folders add.")
            if media not in _HTML_TYPES and media not in _TEXT_TYPES and not media.startswith("text/"):
                raise WebError(f"That link is a {media or 'file of unknown type'}, not a page Kiki can read.")
            data, truncated = _read_capped(response)
        return _page(requested, current, media, charset, data, truncated, note)
    raise WebError(f"Too many redirects (more than {MAX_REDIRECTS}).")


def _read_capped(response: httpx.Response) -> tuple[bytes, bool]:
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_bytes():
        room = MAX_PAGE_BYTES - size
        if len(chunk) >= room:
            chunks.append(chunk[:room])
            return b"".join(chunks), True
        chunks.append(chunk)
        size += len(chunk)
    return b"".join(chunks), False


def _page(
    requested: str, fetched_from: str, media: str, charset: str | None,
    data: bytes, truncated: bool, note: str | None,
) -> WebPage:
    fallback_title = unquote(urlsplit(requested).path.rstrip("/").rsplit("/", 1)[-1]).replace("_", " ")
    if media in _HTML_TYPES:
        title, paragraphs = html_text(data, charset)
        if "wikipedia.org" in (urlsplit(fetched_from).hostname or ""):
            # Footnote markers and edit links are noise in every paragraph.
            paragraphs = [re.sub(r"\[(?:\d+|[a-z]|edit|citation needed)\]", "", text).strip()
                          for text in paragraphs]
            paragraphs = [text for text in paragraphs if text]
        blocks = list(enumerate(paragraphs, start=1))
        kind = "paragraph"
    else:
        text = data.decode(charset or "utf-8", errors="replace")
        blocks = [(number, line.rstrip()) for number, line in enumerate(text.splitlines(), start=1)
                  if line.strip()]
        title = None
        kind = "line"
    if not blocks:
        raise WebError("The page has no readable text. It may build its content with JavaScript, "
                       "which Kiki doesn't run.")
    return WebPage(
        url=requested,
        fetched_from=fetched_from,
        title=title or fallback_title or (urlsplit(requested).hostname or requested),
        blocks=blocks,
        location_kind=kind,
        size=len(data),
        truncated=truncated,
        note=note,
    )


def _append_log(path: Path, record: dict[str, object]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass  # A log that can't be written must not break reading the page.


_STOP_WORDS = {
    "a", "an", "and", "are", "about", "anything", "can", "describe", "details", "does", "did",
    "else", "explain", "for", "from", "give", "how", "info", "information", "into", "is", "it",
    "its", "key", "list", "main", "me", "mean", "more", "of", "on", "or", "page", "point",
    "points", "say", "says", "something", "summarize", "summary", "tell", "that", "the",
    "this", "to", "was", "were", "what", "when", "where", "which", "who", "why", "with", "you",
}


def _terms(text: str) -> list[str]:
    # Six-letter prefixes act as a cheap stemmer: "releases" and "released" match,
    # while "interactive" and "interpreter" stay apart (five letters merged them).
    # Version numbers like "3.14" stay whole; splitting them would drop both halves.
    return [word if word[0].isdigit() else word[:6]
            for word in re.findall(r"\d+(?:\.\d+)+|\w+", text.casefold())
            if (len(word) > 2 or "." in word) and word not in _STOP_WORDS]


@dataclass(frozen=True)
class _Passage:
    start: int
    end: int
    text: str


def page_passages(page: WebPage, size: int = PASSAGE_CHARACTERS) -> list[_Passage]:
    """Consecutive blocks joined up to `size` characters; long blocks are split at sentences."""
    passages: list[_Passage] = []
    current: list[tuple[int, str]] = []
    length = 0

    def flush() -> None:
        nonlocal current, length
        if current:
            joiner = "\n" if page.location_kind == "line" else "\n\n"
            passages.append(_Passage(current[0][0], current[-1][0], joiner.join(t for _, t in current)))
        current, length = [], 0

    for number, text in page.blocks:
        pieces = [text] if len(text) <= size else _split_long(text, size)
        for piece in pieces:
            if current and length + len(piece) > size:
                flush()
            current.append((number, piece))
            length += len(piece)
    flush()
    return passages


def _split_long(text: str, size: int) -> list[str]:
    pieces: list[str] = []
    current = ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        while len(sentence) > size:
            pieces.append(sentence[:size])
            sentence = sentence[size:]
        if current and len(current) + len(sentence) + 1 > size:
            pieces.append(current)
            current = ""
        current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return pieces


class PageSearch:
    """A search backend over one page, so the usual answer loop can cite it.

    With `overview`, the first search returns the opening passages in order,
    for "what is this page about" requests that share no words with the page.
    """

    def __init__(self, page: WebPage, *, overview: bool = False) -> None:
        self.page = page
        self.passages = page_passages(page)
        self._overview = overview
        self._words = [_terms(item.text) for item in self.passages]
        self._counts = [Counter(words) for words in self._words]
        self._pairs = [set(zip(words, words[1:])) for words in self._words]
        self._document_frequency = Counter(term for counts in self._counts for term in counts)
        self._average_length = max(1.0, sum(map(len, self._words)) / max(1, len(self._words)))

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        if self._overview:
            self._overview = False
            chosen = [(0.0, index) for index in range(min(limit, len(self.passages)))]
        else:
            words = _terms(query)
            terms = list(dict.fromkeys(words))
            pairs = set(zip(words, words[1:]))
            total = len(self.passages)
            scored = []
            for index, counts in enumerate(self._counts):
                # BM25, so long word lists (menus, tables of contents) don't win on
                # bulk, plus a bonus for each query phrase found word for word.
                norm = 1.2 * (0.25 + 0.75 * len(self._words[index]) / self._average_length)
                score = sum(
                    math.log(1 + (total - self._document_frequency[term] + 0.5)
                             / (self._document_frequency[term] + 0.5))
                    * counts[term] * 2.2 / (counts[term] + norm)
                    for term in terms if counts[term]
                )
                if score:
                    score += 1.5 * len(pairs & self._pairs[index])
                scored.append((score, index))
            matched = [item for item in scored if item[0] > 0]
            matched.sort(key=lambda item: (-item[0], item[1]))
            chosen = matched[:limit] or [(0.0, index) for index in range(min(limit, total))]
        return [self._result(index, score) for score, index in chosen]

    def unmatched_words(self, question: str) -> list[str]:
        """Question words the page barely covers, when no passage matches most of them.

        Empty when some passage contains at least 60% of the question's words.
        Search always returns something, so without this note a passage that
        shares one word with the question looks like an answer.
        """
        words = {}
        for word in re.findall(r"\d+(?:\.\d+)+|\w+", question):
            for term in _terms(word):
                words.setdefault(term, word)
        if not words or not self._counts:
            return []
        best = max(self._counts, key=lambda counts: sum(term in counts for term in words))
        if sum(term in best for term in words) >= 0.6 * len(words):
            return []
        return [word for term, word in words.items() if term not in best]

    def _result(self, index: int, score: float) -> SearchResult:
        passage = self.passages[index]
        return SearchResult(
            source_id=self.page.source_id,
            path=self.page.url,
            location_kind=self.page.location_kind,
            start_location=passage.start,
            end_location=passage.end,
            excerpt=passage.text,
            score=round(score, 4),
            title=self.page.title,
            ranker="page",
        )
