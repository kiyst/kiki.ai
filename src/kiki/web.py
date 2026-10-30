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
import time
import zlib
from bisect import bisect_right
from collections import Counter
from collections.abc import Callable
import unicodedata
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, unquote, urlencode, urljoin, urlsplit

import httpx

from .documents import html_document
from .retrieval import SearchResult

MAX_PAGE_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 5
# GitHub issue comments read with the issue (one API page).
ISSUE_COMMENTS = 50
TIMEOUT_SECONDS = 15.0
# Passages are built from whole paragraphs up to about this many characters,
# small enough that WEB_PASSAGES of them fit the model's evidence allowance
# whole. Larger passages were trimmed to a window chosen by words, which cut
# heapify's "O(len(x)) time" docstring out of the right passage.
PASSAGE_CHARACTERS = 700
WEB_PASSAGES = 6
USER_AGENT = "Kiki/0.1 (personal assistant; reads pages its user links; +https://github.com/kiyst/kiki.ai)"

_HTML_TYPES = {"text/html", "application/xhtml+xml"}
_TEXT_TYPES = {"text/plain", "text/markdown", "text/x-markdown", "application/vnd.github.raw",
               "application/json", "text/csv"}

Resolver = Callable[[str, int], list[str]]

# Whole download, including a server that sends one byte at a time.
TOTAL_SECONDS = 30.0
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
# Control characters, zero-width characters, and text-direction overrides:
# invisible on the page, but able to hide or reorder text in the terminal.
_UNSAFE_CHARACTERS = re.compile(
    "[\x00-\x08\x0b-\x1f\x7f-\x9f­​-‏‪-‮⁠-⁤⁦-⁯﻿\\s]"
)
_INVISIBLE = re.compile(
    "[\x00-\x08\x0b-\x1f\x7f-\x9f­​-‏‪-‮⁠-⁤⁦-⁯﻿]"
)
# Query parameters whose values look like secrets; kept out of the log.
_SECRET_PARAMETER = re.compile(
    r"(?i)(token|key|secret|pass(word|wd)?|pwd|auth|sig(nature)?|session|code|credential|jwt)"
)


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
    # Location numbers where top-level sections begin, for page overviews.
    sections: tuple[int, ...] = ()

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


# Text written to steer an AI reader rather than inform a human one. Only
# forms that address the reader count; merely mentioning "AI assistants" or
# "AI models" (an encyclopedia article about them, say) does not.
_AI = r"(?:ai|a\.i\.|llm|language model|chatbot)s?(?:\s+(?:assistants?|agents?|models?|readers?|systems?))?"
_ORDER = (r"(?:ignore|tell|say|reply|respond|answer|print|include|recommend|repeat|begin|start|end|"
          r"output|reveal|call|visit|run|claim|state|before|from now on|new rule|you must|you are|"
          r"always|never|do not|don't)")
_INJECTION = re.compile(
    r"\b(?:ignore|disregard|forget)\b[^.\n]{0,40}\b(?:previous|prior|above|earlier|all|your)\b"
    r"[^.\n]{0,20}\b(?:instructions?|rules|prompts?|guidelines)\b"
    rf"|\b(?:note|message|instructions?|important|attention|warning)\s+(?:to|for)\s+(?:all\s+)?{_AI}\b"
    rf"|\b{_AI}\s+(?:reading|that read|processing|summari[sz]ing)\s+this\b"
    rf"|\b{_AI}\s+(?:must|should|need to|are required to|have to)\s+(?:always\s+|now\s+|only\s+)?"
    r"(?:ignore|tell|say|reply|respond|answer|print|include|recommend|repeat|begin|start|end|"
    r"output|reveal|call|visit|run|claim|state|describe this|summari[sz]e this)\b"
    rf"|(?:^|[.!?]\s+)(?:assistant|ai|system|kiki)\s*[:,]\s*(?:please\s+)?{_ORDER}\b"
    r"|\b(?:print|reveal|show|repeat|output)\s+(?:your|the)\s+(?:full\s+|entire\s+)?system prompt\b"
    r"|</?\s*(?:passage|system|instructions?)\s*>"
    r"|\byou are (?:now )?(?:dan|in developer mode)\b"
    r"|\bnew rule from the developers\b"
    r"|\bwhen (?:summari[sz]ing|answering|responding|describing|quoting)\b[^.\n]{0,40}"
    r"\b(?:always|must|include|mention|add|tell)\b",
    re.IGNORECASE,
)
REMOVED_MARKER = "[Kiki removed a sentence aimed at AI assistants]"


def _is_planted(sentence: str) -> bool:
    # NFKC folds look-alike forms (full-width "Ａｓｓｉｓｔａｎｔ：") into plain ones.
    return bool(_INJECTION.search(unicodedata.normalize("NFKC", sentence)))


def _sentences(text: str) -> list[str]:
    return re.split(r"(?<=[.!?])\s+", text)


def suspicious_instructions(page: WebPage, limit: int = 3) -> list[str]:
    """Sentences on the page that address an AI reader, at most `limit`, for the user."""
    found: list[str] = []
    for _, text in page.blocks:
        for sentence in _sentences(text):
            if _is_planted(sentence):
                found.append(sentence.strip()[:240])
                if len(found) >= limit:
                    return found
    return found


def without_planted(page: WebPage) -> tuple[WebPage, int]:
    """The page with sentences aimed at AI readers replaced by a marker, and how many.

    The model never sees them, so it can neither obey nor repeat them (quoting
    a planted link or command back, even with a warning, still puts it in
    front of the user). Quoting them in the model's instructions instead made
    it obey one: text placed among instructions borrows their authority."""
    removed = 0
    blocks: list[tuple[int, str]] = []
    for number, text in page.blocks:
        kept = []
        for sentence in _sentences(text):
            if _is_planted(sentence):
                removed += 1
                kept.append(REMOVED_MARKER)
            else:
                kept.append(sentence)
        blocks.append((number, " ".join(kept)))
    return (replace(page, blocks=blocks) if removed else page), removed


def looks_like_url(text: str) -> bool:
    # A bare address needs a letter top-level domain, so "python3.14" is a word, not a site.
    return bool(re.match(r"^(https?://\S+|([\w-]+\.)+[a-z]{2,}(:\d+)?([/?#]\S*)?)$", text, re.I))


def normalize_url(text: str) -> str:
    text = text.strip().strip("<>")
    if _UNSAFE_CHARACTERS.search(text) or "\\" in text:
        # Spaces, control characters, and backslashes are read differently by
        # different URL parsers, a classic way to slip past an address check.
        raise WebError("That address contains spaces, backslashes, or control characters.")
    if not re.match(r"^[a-z][a-z0-9+.-]*://", text, re.I):
        text = "https://" + text
    parts = urlsplit(text)
    if parts.scheme.casefold() not in {"http", "https"}:
        raise WebError("Kiki only reads http:// and https:// addresses.")
    if "@" in parts.netloc:
        raise WebError("Addresses with a username or password in them aren't supported.")
    if not parts.hostname:
        raise WebError(f"That doesn't look like a web address: {text}")
    try:
        parts.port
    except ValueError as exc:
        raise WebError(f"That address has an invalid port: {text}") from exc
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


def _public_address(url: str, resolver: Resolver) -> str:
    """The checked address to connect to; every address the name has must be public.

    Kiki then connects to exactly this address, so a DNS server that answers
    differently the second time (DNS rebinding) can't redirect the request
    to the user's own computer or network."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    port = parts.port or (443 if parts.scheme == "https" else 80)
    addresses = resolver(host, port)
    if not addresses:
        raise WebError(f"Couldn't find {host}.")
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
        if not _is_public(ip):
            raise WebError(
                f"{host} points to your own computer or local network ({ip}). "
                "Kiki only reads public web pages."
            )
    return addresses[0].split("%", 1)[0]


def _is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if not ip.is_global:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        # IPv6 forms that carry an IPv4 address inside (IPv4-mapped, 6to4,
        # Teredo, NAT64) are only as public as the address they carry.
        embedded = [ip.ipv4_mapped, ip.sixtofour, *(ip.teredo or ())]
        if ip in _NAT64:
            embedded.append(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
        return all(inner.is_global for inner in embedded if inner is not None)
    return True


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
                                 "requested": _redacted(requested)}
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
    except (httpx.InvalidURL, ValueError, UnicodeError, RecursionError) as exc:
        # Addresses and responses that the parsers reject, reported rather than crashing.
        record.update(status="refused or failed", reason=type(exc).__name__)
        raise WebError(f"Kiki couldn't use that address or response ({type(exc).__name__}).") from exc
    finally:
        if owned:
            client.close()
        if log is not None:
            _append_log(log, record)


@dataclass(frozen=True)
class _Response:
    url: str
    media: str
    charset: str | None
    data: bytes
    truncated: bool


def _download(
    client: httpx.Client,
    requested: str,
    target: str,
    headers: dict[str, str],
    note: str | None,
    resolver: Resolver,
    record: dict[str, object],
) -> WebPage:
    issue = _github_issue(requested)
    if issue:
        return _issue_page(client, requested, *issue, resolver, record)
    got = _get(client, requested, target, headers, resolver, record, check_media=_readable_media)
    return _page(requested, got.url, got.media, got.charset, got.data, got.truncated, note)


def _readable_media(media: str) -> None:
    if media == "application/pdf":
        raise WebError("That link is a PDF. Kiki can't read PDFs from the web yet; "
                       "download it and add its folder with /folders add.")
    if media not in _HTML_TYPES and media not in _TEXT_TYPES and not media.startswith("text/"):
        raise WebError(f"That link is a {media or 'file of unknown type'}, not a page Kiki can read.")


def _get(
    client: httpx.Client,
    requested: str,
    target: str,
    headers: dict[str, str],
    resolver: Resolver,
    record: dict[str, object],
    *,
    check_media: Callable[[str], None] | None = None,
) -> _Response:
    """One GET, following redirects only to public addresses; errors become WebError.

    The type is checked from the headers before anything is downloaded, so a
    link to a large file costs nothing."""
    hops = record.setdefault("fetched", [])
    assert isinstance(hops, list)
    current = target
    deadline = time.monotonic() + TOTAL_SECONDS
    for _ in range(MAX_REDIRECTS + 1):
        address = _public_address(current, resolver)
        hops.append(_redacted(current))
        parts = urlsplit(current)
        url = httpx.URL(current)
        pinned = url.copy_with(host=address)
        # International names travel in their ASCII (punycode) form.
        extensions = {"sni_hostname": url.raw_host.decode("ascii")} if parts.scheme == "https" else {}
        with client.stream(
            "GET",
            pinned,
            headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate",
                     "Host": url.netloc.decode("ascii"), **headers},
            follow_redirects=False,
            extensions=extensions,
        ) as response:
            if response.is_redirect and response.headers.get("location"):
                current = normalize_url(urljoin(current, response.headers["location"]))
                continue
            record["http_status"] = response.status_code
            host = parts.hostname
            if response.status_code == 404:
                raise WebError(f"That page doesn't exist (404): {requested}")
            if host == "api.github.com" and response.headers.get("x-ratelimit-remaining") == "0":
                raise WebError("GitHub's limit for readers who aren't signed in (60 requests an "
                               "hour) is used up; try again later.")
            if response.status_code in {401, 403}:
                raise WebError(f"{host} refused the request ({response.status_code}); "
                               "it may need a login or block automated readers.")
            if response.status_code == 429:
                raise WebError(f"{host} says too many requests; try again later.")
            if response.status_code >= 400:
                raise WebError(f"{host} answered with an error ({response.status_code}).")
            media = response.headers.get("content-type", "").split(";", 1)[0].strip().casefold()
            if check_media:
                check_media(media)
            data, truncated = _read_capped(response, deadline)
            return _Response(current, media, response.charset_encoding, data, truncated)
    raise WebError(f"Too many redirects (more than {MAX_REDIRECTS}).")


def _github_issue(url: str) -> tuple[str, str, int] | None:
    parts = urlsplit(url)
    if (parts.hostname or "").casefold() not in {"github.com", "www.github.com"}:
        return None
    match = re.fullmatch(r"/([^/]+)/([^/]+)/(?:issues|pull)/(\d+)/?", parts.path)
    return (unquote(match.group(1)), unquote(match.group(2)), int(match.group(3))) if match else None


def _issue_page(
    client: httpx.Client, requested: str, owner: str, repo: str, number: int,
    resolver: Resolver, record: dict[str, object],
) -> WebPage:
    """A GitHub issue or pull request and its first comments, through GitHub's API.

    The web page builds its conversation with JavaScript, so it reads as
    almost empty; the API returns the same text directly."""
    api = f"https://api.github.com/repos/{quote(owner)}/{quote(repo)}/issues/{number}"
    headers = {"Accept": "application/vnd.github+json"}
    issue_response = _get(client, requested, api, headers, resolver, record, check_media=_json_media)
    comments_response = _get(client, requested, f"{api}/comments?per_page={ISSUE_COMMENTS}",
                             headers, resolver, record, check_media=_json_media)
    try:
        issue = json.loads(issue_response.data)
        comments = json.loads(comments_response.data) if not comments_response.truncated else []
        if not isinstance(issue, dict):
            raise ValueError("not an issue")
    except (ValueError, RecursionError) as exc:
        raise WebError("GitHub returned something Kiki couldn't read.") from exc
    def text(value: object) -> str:
        return _INVISIBLE.sub("", value).strip() if isinstance(value, str) else ""

    def login(item: dict[str, Any]) -> str:
        user = item.get("user")
        return text(user.get("login")) if isinstance(user, dict) else ""

    title = text(issue.get("title"))[:200]
    kind = "Pull request" if "pull_request" in issue else "Issue"
    blocks: list[str] = [f"{title} (#{number})"]
    labels = ", ".join(text(label.get("name")) for label in issue.get("labels") or []
                       if isinstance(label, dict))
    blocks.append(f"{kind} · {text(issue.get('state')) or 'unknown'} · opened by "
                  f"{login(issue) or 'someone'} on {text(issue.get('created_at'))[:10]}"
                  + (f" · labels: {labels}" if labels else ""))
    sections = [1]
    blocks.extend(_markdown_paragraphs(text(issue.get("body"))))
    comments = [item for item in comments if isinstance(item, dict)] if isinstance(comments, list) else []
    for comment in comments:
        sections.append(len(blocks) + 1)
        blocks.append(f"Comment by {login(comment) or 'someone'} on "
                      f"{text(comment.get('created_at'))[:10]}:")
        blocks.extend(_markdown_paragraphs(text(comment.get("body"))))
    shown = len(comments)
    total = issue.get("comments") if isinstance(issue.get("comments"), int) else shown
    note = "Reading the conversation through GitHub's API."
    if total > shown:
        note += f" Only the first {shown} of {total} comments are included."
    return WebPage(
        url=requested,
        fetched_from=api,
        title=f"{owner}/{repo} #{number}: {title}",
        blocks=list(enumerate(blocks, start=1)),
        location_kind="paragraph",
        size=len(issue_response.data) + len(comments_response.data),
        truncated=issue_response.truncated,
        note=note,
        sections=tuple(sections),
    )


def _json_media(media: str) -> None:
    if media != "application/json":
        raise WebError("GitHub returned something other than the expected data.")


def _markdown_paragraphs(text: str) -> list[str]:
    """Paragraphs of a Markdown body; a fenced code block stays in one piece."""
    paragraphs: list[str] = []
    for piece in re.split(r"(```.*?```)", text.replace("\r\n", "\n"), flags=re.DOTALL):
        if piece.startswith("```"):
            paragraphs.append(piece.strip())
        else:
            paragraphs.extend(part.strip() for part in re.split(r"\n\s*\n", piece) if part.strip())
    return paragraphs


def _read_capped(response: httpx.Response, deadline: float) -> tuple[bytes, bool]:
    """At most MAX_PAGE_BYTES of decoded content, decompressing only that much.

    Decompression is done here rather than by httpx so a small compressed
    response that expands to gigabytes (a "zip bomb") stops at the cap
    instead of filling memory."""
    encoding = response.headers.get("content-encoding", "").strip().casefold()
    if response.is_stream_consumed:
        # Already read and decoded in full (a test transport, for instance).
        raw_chunks, decoder = iter([response.content]), None
    elif encoding in {"", "identity"}:
        raw_chunks, decoder = response.iter_raw(), None
    elif encoding in {"gzip", "x-gzip", "deflate"}:
        # gzip or zlib framing, detected from the data.
        raw_chunks, decoder = response.iter_raw(), zlib.decompressobj(47)
    else:
        raise WebError(f"The page is compressed in a way Kiki can't read ({encoding}).")
    chunks: list[bytes] = []
    size = 0
    try:
        for raw in raw_chunks:
            if time.monotonic() > deadline:
                raise WebError(f"The page took more than {TOTAL_SECONDS:.0f} seconds to download.")
            pending = raw
            while pending:
                room = MAX_PAGE_BYTES - size
                if decoder is None:
                    piece, pending = pending, b""
                else:
                    piece = decoder.decompress(pending, room + 1)
                    pending = decoder.unconsumed_tail
                chunks.append(piece)
                size += len(piece)
                if size > MAX_PAGE_BYTES:
                    return b"".join(chunks)[:MAX_PAGE_BYTES], True
        if decoder is not None:
            chunks.append(decoder.flush())
    except zlib.error as exc:
        raise WebError("The page's compression is damaged.") from exc
    data = b"".join(chunks)
    return data[:MAX_PAGE_BYTES], len(data) > MAX_PAGE_BYTES


def _page(
    requested: str, fetched_from: str, media: str, charset: str | None,
    data: bytes, truncated: bool, note: str | None,
) -> WebPage:
    fallback_title = unquote(urlsplit(requested).path.rstrip("/").rsplit("/", 1)[-1]).replace("_", " ")
    sections: list[int] = []
    if media in _HTML_TYPES:
        title, paragraphs, headings = html_document(data, charset, main_only=True, skip_hidden=True)
        wikipedia = "wikipedia.org" in (urlsplit(fetched_from).hostname or "")
        blocks = []
        for index, text in enumerate(paragraphs):
            text = _INVISIBLE.sub("", text)
            if wikipedia:
                # Footnote markers and edit links are noise in every paragraph.
                text = re.sub(r"\[(?:\d+|[a-z]|edit|citation needed)\]", "", text).strip()
            # Documentation generators end headings with a link symbol.
            text = text.rstrip("¶").rstrip()
            if not text:
                continue
            blocks.append((len(blocks) + 1, text))
            if index in headings:
                sections.append(len(blocks))
        kind = "paragraph"
    else:
        try:
            text = data.decode(charset or "utf-8", errors="replace")
        except LookupError:  # a made-up charset name
            text = data.decode("utf-8", errors="replace")
        lines = [_INVISIBLE.sub("", line) for line in text.splitlines()]
        blocks = [(number, line.rstrip()) for number, line in enumerate(lines, start=1)
                  if line.strip()]
        sections = _text_sections(lines)
        title = None
        kind = "line"
    if not blocks:
        raise WebError("The page has no readable text. It may build its content with JavaScript, "
                       "which Kiki doesn't run.")
    title = _INVISIBLE.sub("", title or "").strip()[:200]
    return WebPage(
        url=requested,
        fetched_from=fetched_from,
        title=title or fallback_title or (urlsplit(requested).hostname or requested),
        blocks=blocks,
        location_kind=kind,
        size=len(data),
        truncated=truncated,
        note=note,
        sections=tuple(sections),
    )


def _text_sections(lines: list[str]) -> list[int]:
    """Line numbers of Markdown ("## Title") and reStructuredText (underlined) headings."""
    starts = []
    for index, line in enumerate(lines):
        underline = lines[index + 1].strip() if index + 1 < len(lines) else ""
        if re.match(r"#{1,2}\s+\S", line) or (
            line.strip() and len(underline) >= 3 and set(underline) <= {"=", "-"}
        ):
            starts.append(index + 1)
    return starts


def secret_parameters(url: str) -> list[str]:
    """Names of query parameters that look like tokens or passwords."""
    return [name for name, _ in parse_qsl(urlsplit(url).query, keep_blank_values=True)
            if _SECRET_PARAMETER.search(name)]


def _redacted(url: str) -> str:
    """The address with secret-looking query values replaced, for the log."""
    parts = urlsplit(url)
    if not parts.query:
        return url
    pairs = [(name, "REDACTED" if _SECRET_PARAMETER.search(name) else value)
             for name, value in parse_qsl(parts.query, keep_blank_values=True)]
    return parts._replace(query=urlencode(pairs)).geturl()


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


QueryEmbedder = Callable[[str], list[float]]
# Sections an overview skips: lists of sources and links, not content.
_BACK_MATTER = {
    "bibliography", "citations", "contents", "external links", "footnotes", "further reading",
    "license", "notes", "notes and references", "references", "see also", "sources",
    "table of contents", "works cited",
}
# Best passage similarity (qwen3-embedding, cosine) below which a page almost
# certainly doesn't cover the question. Measured on three real pages: off-topic
# questions scored 0.19-0.24 at best, on-topic ones 0.43-0.86, including
# reworded ones ("is python slow?").
OFF_TOPIC_SIMILARITY = 0.35


class PageSearch:
    """A search backend over one page, so the usual answer loop can cite it.

    With `overview`, the first search returns the opening passages in order,
    for "what is this page about" requests that share no words with the page.

    With passage `vectors` and an `embed_query` function, passages are picked
    by meaning as well as by words (the two rankings merged, as for indexed
    documents), so "how fast is heapify?" can find "O(len(x)) time".
    """

    def __init__(
        self,
        page: WebPage,
        *,
        overview: bool = False,
        vectors: list[list[float]] | None = None,
        embed_query: QueryEmbedder | None = None,
    ) -> None:
        self.page = page
        self.passages = page_passages(page)
        if vectors is not None and len(vectors) != len(self.passages):
            raise ValueError("one vector per passage is required")
        self._vectors = vectors if embed_query else None
        self._embed_query = embed_query
        self.meaning_error: str | None = None
        self._query_vectors: dict[str, list[float]] = {}
        self._overview = overview
        self._words = [_terms(item.text) for item in self.passages]
        self._counts = [Counter(words) for words in self._words]
        self._pairs = [set(zip(words, words[1:])) for words in self._words]
        self._document_frequency = Counter(term for counts in self._counts for term in counts)
        self._average_length = max(1.0, sum(map(len, self._words)) / max(1, len(self._words)))

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        if self._overview:
            self._overview = False
            chosen = [(0.0, index) for index in self._overview_indexes(limit)]
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
            similarities = self.similarities(query)
            if similarities is not None:
                by_meaning = sorted(range(total), key=lambda index: (-similarities[index], index))
                fused: dict[int, float] = {}
                for ranking in ([index for _, index in matched], by_meaning):
                    for rank, index in enumerate(ranking, start=1):
                        fused[index] = fused.get(index, 0.0) + 1.0 / (60 + rank)
                order = sorted(fused, key=lambda index: (-fused[index], index))
                chosen = [(fused[index], index) for index in order[:limit]]
            else:
                chosen = matched[:limit] or [(0.0, index) for index in range(min(limit, total))]
        return [self._result(index, score) for score, index in chosen]

    def _overview_indexes(self, limit: int) -> list[int]:
        """The opening passages plus the start of sections spread across the page,
        so an overview covers the whole page rather than its introduction."""
        total = len(self.passages)
        lead = list(range(min(total, max(1, (limit + 1) // 2))))
        text_at = dict(self.page.blocks)
        ends = [item.end for item in self.passages]
        starts: list[int] = []
        for number in self.page.sections:
            heading = text_at.get(number, "").strip("#=- ").casefold()
            if heading in _BACK_MATTER:
                continue
            # The passage holding the section's first content, not just its heading.
            index = bisect_right(ends, number)
            if index < total and index not in lead and (not starts or starts[-1] != index):
                starts.append(index)
        room = limit - len(lead)
        picks: list[int] = []
        if starts and room > 0:
            step = len(starts) / room
            picks = list(dict.fromkeys(starts[int(k * step)] for k in range(min(room, len(starts)))))
        chosen = set(lead) | set(picks)
        # Pages without headings (or few of them) continue from the opening.
        for index in range(total):
            if len(chosen) >= limit:
                break
            chosen.add(index)
        return sorted(chosen)[:limit]

    def similarities(self, query: str) -> list[float] | None:
        """Cosine similarity of the query to every passage, or None without vectors."""
        if self._vectors is None or self._embed_query is None:
            return None
        if query not in self._query_vectors:
            try:
                self._query_vectors[query] = self._embed_query(query)
            except Exception as exc:
                # Word matching still works; meaning is an improvement, not a requirement.
                self._vectors = None
                self.meaning_error = str(exc) or type(exc).__name__
                return None
        return [_cosine(self._query_vectors[query], vector) for vector in self._vectors]

    def probably_off_topic(self, question: str) -> bool | None:
        """True when no passage is close in meaning; None without vectors."""
        similarities = self.similarities(question)
        if not similarities:
            return None
        return max(similarities) < OFF_TOPIC_SIMILARITY

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
        ranker = "page" if self._vectors is None else "page-hybrid"
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
            ranker=ranker,
        )


def embed_passages(
    texts: list[str], embed: Callable[[list[str]], list[list[float]]], batch: int = 16
) -> list[list[float]]:
    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch):
        vectors.extend(embed(texts[start : start + batch]))
    return vectors


def _cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    norm = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return dot / norm if norm else 0.0
