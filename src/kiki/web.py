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
import threading
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

from .documents import html_document, safe_charset
from .extraction import ExtractionError
from .isolation import parse_html_isolated
from .retrieval import SearchResult
from .safety import offline_mode

# Pages up to this size parse in-process; larger ones go to a limited child
# process. At 32 KB a crafted page ("<a" and a tab, repeated) took about a minute in
# Python's parser (re-audit); at 4 KB the worst known input takes well under
# a second.
IN_PROCESS_HTML_BYTES = 4 * 1024

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
# The whole fetch (headers and redirects too) ends this long after TOTAL_SECONDS.
WATCHDOG_MARGIN_S = 5.0
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_LOCAL_NAT64 = ipaddress.ip_network("64:ff9b:1::/48")
_IPV4_COMPATIBLE = ipaddress.ip_network("::/96")
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
    r"(?i)(token|key|secret|pass(word|wd)?|pwd|auth|sig(nature)?|session|code|credential|jwt|access)"
    # Short names commonly carrying tokens (?t=…, ?k=…; re-audit).
    r"|^(?:t|k|at|st|sid|tk|pw)$"
)


class WebError(ValueError):
    """A page Kiki will not or cannot read; the message is meant for the user."""




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
    r"\b(?:always|must|include|mention|add|tell)\b"
    # Added after the audit's bypasses (A23).
    r"|\bignore (?:everything|anything|all)\s+(?:above|before|else|prior)\b"
    rf"|\bdear\s+(?:{_AI}|assistant|model)\b"
    r"|\bbefore (?:you )?(?:answer|respond|reply)(?:ing)?\b[^.\n]{0,15},?\s*(?:add|say|include|tell|mention|"
    r"print|state|recommend)\b"
    r"|\b(?:important|attention|note)\s+(?:for|to)\s+(?:the\s+)?(?:model|assistant|ai)\b"
    # Added after the re-audit's bypasses.
    r"|\b(?:ignore|disregard|forget)\s+(?:the|everything|anything|all)\s+(?:text\s+)?"
    r"(?:above|before|previous|prior|earlier)\s*(?:[.,;:!]|$|and\b)"
    r"|\bforget (?:everything|all|what) you (?:were|have been|'ve been|was) (?:told|given|instructed)\b"
    rf"|\b(?:hey|hi|hello|ok|okay|yo)\s+(?:{_AI}|assistant|kiki|chatgpt|claude|gemini|copilot)\s*[,:!.]?\s*"
    rf"(?:please\s+)?{_ORDER}\b"
    rf"|\bif you(?:'re| are)\s+(?:an?\s+)?(?:{_AI}|assistant|bot|language model)\b"
    r"|\bsystem\s+(?:override|prompt|instructions?)\s*:",
    re.IGNORECASE,
)
REMOVED_MARKER = "[Kiki removed a sentence aimed at AI assistants]"
# Latin look-alikes from Cyrillic and Greek, which NFKC leaves alone
# ("Іgnore" with a Cyrillic І slipped past the detector, audit A23).
_CONFUSABLES = str.maketrans(
    "АВЕКМНОРСТХаеорсухіІјЈѕЅԁӏΑΒΕΖΗΙΚΜΝΟΡΤΥΧαοριυνκпгһԝɡ",
    "ABEKMHOPCTXaeopcyxiIjJsSdlABEZHIKMNOPTYXaopiuvknrhwg",
)


def _is_planted(sentence: str) -> bool:
    # NFKC folds width variants (full-width "Ａｓｓｉｓｔａｎｔ："); the table
    # folds letters from other scripts that look Latin.
    # Zero-width characters are dropped first: "Ign​ore" in an indexed
    # document reached the detector intact (re-audit; web pages strip them earlier).
    folded = unicodedata.normalize("NFKC", _INVISIBLE.sub("", sentence)).translate(_CONFUSABLES)
    return bool(_INJECTION.search(folded))


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
    found.extend(" ".join(fragment for _, fragment, _ in split)[:240]
                 for split in _split_instructions(page.blocks))
    return found[:limit]


# A middle block this short can be one piece of an instruction split over
# three lines; longer ones are ordinary paragraphs.
_SPLIT_MIDDLE_CHARACTERS = 80


def _split_instructions(blocks: list[tuple[int, str]]) -> list[list[tuple[int, str, str]]]:
    """Instructions split across two or three blocks (line breaks or <br>
    between the pieces). Each is a list of (block index, fragment, where):
    "tail" ends its block, "whole" is the block, "head" starts it."""
    found: list[list[tuple[int, str, str]]] = []
    used: set[int] = set()
    for index in range(len(blocks) - 1):
        if index in used:
            continue
        first = _sentences(blocks[index][1])[-1]
        if not first or _is_planted(first):
            continue
        candidates = [[(index, first, "tail"), (index + 1, _sentences(blocks[index + 1][1])[0], "head")]]
        middle = blocks[index + 1][1]
        if (index + 2 < len(blocks) and len(middle) <= _SPLIT_MIDDLE_CHARACTERS
                and len(_sentences(middle)) == 1):
            candidates.append([(index, first, "tail"), (index + 1, middle, "whole"),
                               (index + 2, _sentences(blocks[index + 2][1])[0], "head")])
        # The longest split first, so "Note to" / "AI" / "assistants: ..." loses all three pieces.
        for pieces in reversed(candidates):
            if (all(fragment for _, fragment, _ in pieces)
                    and not any(_is_planted(fragment) for _, fragment, _ in pieces[1:])
                    and _is_planted(" ".join(fragment for _, fragment, _ in pieces))):
                found.append(pieces)
                used.update(position for position, _, _ in pieces)
                break
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
        cleaned, count = remove_planted_text(text)
        removed += count
        blocks.append((number, cleaned))
    # An instruction split over two or three blocks: every piece goes (audit A23).
    for split in _split_instructions(blocks):
        for position, fragment, where in split:
            number, text = blocks[position]
            if where == "tail":
                text = text[: len(text) - len(fragment)] + REMOVED_MARKER
            elif where == "head":
                text = REMOVED_MARKER + text[len(fragment):]
            else:
                text = REMOVED_MARKER
            blocks[position] = (number, text)
        removed += 1
    # The title travels with every passage, so it is checked too (audit A10).
    title, count = remove_planted_text(page.title)
    if count:
        removed += count
        title = page.host
    if not removed:
        return page, 0
    return replace(page, blocks=blocks, title=title), removed


def remove_planted_text(text: str) -> tuple[str, int]:
    """Text with each sentence aimed at AI readers replaced by REMOVED_MARKER, and how many."""
    kept: list[str] = []
    removed = 0
    for sentence in _sentences(text):
        if _is_planted(sentence):
            removed += 1
            kept.append(REMOVED_MARKER)
        else:
            kept.append(sentence)
    return (" ".join(kept) if removed else text), removed


# A full stop may end the sentence after a number, but not continue it (3.14.0).
_PHONE = re.compile(r"(?<![\w.])\+?\d[\d ().-]{7,}\d(?!\w|\.\d)")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_LINK = re.compile(
    r"\bhttps?://[^\s)\]>\"'`]+|\bwww\.[^\s)\]>\"'`]+"
    # A bare domain with a path ("evil.example/login"): a link without its scheme.
    r"|(?<![\w@/.-])(?:[a-z0-9-]+\.)+[a-z]{2,24}/[^\s)\]>\"'`]*"
    # A bare domain the user is sent to ("visit evil.example"; re-audit). Only
    # after such a verb: on its own "config.json" or "main.py" looks the same.
    r"|(?<=visit )(?:[a-z0-9-]+\.)+[a-z]{2,24}\b|(?<=go to )(?:[a-z0-9-]+\.)+[a-z]{2,24}\b"
    r"|(?<=open )(?:[a-z0-9-]+\.)+[a-z]{2,24}\b(?!\.)|(?<=log in at )(?:[a-z0-9-]+\.)+[a-z]{2,24}\b"
    r"|(?<=sign in at )(?:[a-z0-9-]+\.)+[a-z]{2,24}\b|(?<=download from )(?:[a-z0-9-]+\.)+[a-z]{2,24}\b"
    r"|(?<=navigate to )(?:[a-z0-9-]+\.)+[a-z]{2,24}\b|(?<=head to )(?:[a-z0-9-]+\.)+[a-z]{2,24}\b",
    re.IGNORECASE)
# Commands that download and run something, or need administrator rights.
_RISKY_COMMAND = re.compile(
    r"\b(?:curl|wget|iwr|invoke-webrequest|invoke-expression|iex|certutil|bitsadmin|mshta|"
    r"regsvr32|sudo|chmod\s+777|rm\s+-rf|del\s+/[sq]|format\s+[a-z]:|reg\s+add|msiexec|rundll32|"
    r"powershell(?:\.exe)?\s+[^\n]*-(?:e|enc|encodedcommand|w|windowstyle)\b|pwsh\s+[^\n]*-(?:e|enc)\b|"
    r"cmd(?:\.exe)?\s+/[ck]|python3?\s+-c|bash\s+-c)\b|\|\s*(?:ba)?sh\b"
    # Added after the re-audit: switching off script protection, elevating,
    # Defender exclusions, and installing packages from somewhere other than
    # the package index.
    r"|-executionpolicy\s+(?:bypass|unrestricted)\b|\bset-executionpolicy\b|-verb\s+runas\b|\brunas\s+/"
    r"|\b(?:add|set)-mppreference\b"
    r"|\bpip3?\s+install\b[^\n`]*(?:https?://|git\+|--(?:extra-)?index-url|--trusted-host)",
    re.IGNORECASE,
)


def risky_details(answer: str, page_url: str) -> list[str]:
    """Phone numbers, emails, other sites' links, and risky commands in a web answer.

    A planted instruction can steer an answer however it is phrased, but what
    it wants passed on is nearly always one of these: a number to call, an
    address to write to, a link, or a command. They are listed for the user
    as unverified, whether or not anything looked like an attack."""
    found: list[str] = []
    for match in _PHONE.finditer(answer):
        number = match.group().strip()
        # Dates (2025-10-07) and year ranges (1815-1852) look like numbers too.
        if (sum(character.isdigit() for character in number) >= 7
                and not re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}|\d{4}\s*-\s*\d{2,4}", number)):
            found.append(f"phone number {number}")
    found.extend(f"email address {match.group()}" for match in _EMAIL.finditer(answer))
    host = (urlsplit(page_url).hostname or "").casefold().removeprefix("www.")
    for match in _LINK.finditer(answer):
        link = match.group().rstrip(".,;:!?")
        target = (urlsplit(link if "://" in link else f"https://{link}").hostname or "").casefold()
        if not host or not (target == host or target.endswith(f".{host}")
                            or target.removeprefix("www.") == host):
            found.append(f"link {link}")
    # Code spans and lines first, so the command itself is reported, not its paragraph.
    pieces = re.findall(r"`([^`\n]+)`", answer) + [
        sentence for line in re.sub(r"`[^`\n]+`", " ", answer).splitlines()
        for sentence in re.split(r"(?<=[.!?])\s+", line)]
    for piece in pieces:
        if _RISKY_COMMAND.search(piece):
            found.append(f"command {piece.strip()[:120]}")
    return list(dict.fromkeys(found))


_CREDENTIAL_REQUEST = re.compile(
    r"\b(?:send(?:ing)?|e-?mail(?:ing)?|enter(?:ing)?|typ(?:e|ing)|shar(?:e|ing)|text(?:ing)?|"
    r"giv(?:e|ing)|submit(?:ting)?|provid(?:e|ing)|reply(?:ing)? with)\b(?:[^.!?\n]|\.(?=\S)){0,60}"
    r"\b(?:password|passwd|passcode|pin|one-time code|verification code|(?:2fa|mfa|otp|sms|security|login) code|"
    r"login credentials|login details|card number|credit card|"
    r"bank details|account number|social security|seed phrase|recovery phrase)\b"
    r"|\b(?:password|passwd|passcode|pin|card number|bank details|seed phrase|credentials|"
    r"(?:2fa|mfa|otp) code)\b(?:[^.!?\n]|\.(?=\S)){0,40}"
    r"\b(?:to|at|via)\b[^.!?\n]{0,20}(?:@|https?://|\+?\d{3})",
    re.IGNORECASE,
)


def asks_for_credentials(answer: str) -> bool:
    """True when an answer tells the user to hand over a password, code, or payment details.

    No legitimate page needs an assistant to relay that; it is the payload of
    phishing pages, so it gets its own warning however it was phrased. A
    sentence warning against it ("never share your password") doesn't count."""
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", answer):
        for match in _CREDENTIAL_REQUEST.finditer(sentence):
            # The negation must govern the request itself ("never share your
            # password"); any "not" anywhere used to disable the warning, as in
            # "Do not delay: email your password to…" (audit A25).
            before = sentence[:match.start()]
            negated = re.search(r"\b(?:never|don't|do not|not|avoid|without)\s+(?:[A-Za-z']+\s+){0,2}$",
                                before, re.IGNORECASE)
            # "Don't hesitate to send…" and "not forget to" urge the request (re-audit).
            urged = re.search(r"\b(?:hesitate|forget|wait|delay)\b[^.!?\n]{0,20}$", before, re.IGNORECASE)
            if not negated or urged:
                return True
    return False


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
    if not ip.is_global or ip.is_multicast or ip.is_reserved:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and (
            ip.is_site_local or ip in _IPV4_COMPATIBLE or ip in _LOCAL_NAT64):
        # Ranges Python 3.12.3 still calls global (audit L4).
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
    # One deadline for the whole fetch, connection, headers, and redirects
    # included: a server dripping headers a byte at a time stayed under each
    # read timeout for hours (audit A28). Closing the client ends the request.
    done, expired = threading.Event(), threading.Event()

    def watchdog() -> None:
        if not done.wait(TOTAL_SECONDS + WATCHDOG_MARGIN_S):
            expired.set()
            client.close()

    threading.Thread(target=watchdog, daemon=True).start()
    host = urlsplit(target).hostname
    try:
        page = _download(client, requested, target, headers, note, resolver, record)
        record.update(status="ok", bytes=page.size)
        return page
    except WebError as exc:
        record.update(status="refused or failed", reason=_redacted_text(str(exc)))
        raise
    except Exception as exc:
        if expired.is_set():
            record.update(status="timeout")
            raise WebError(f"{host} took longer than {TOTAL_SECONDS:.0f} s; Kiki stopped waiting.") from exc
        if isinstance(exc, httpx.TimeoutException):
            record.update(status="timeout")
            raise WebError(f"{host} took too long to answer.") from exc
        if isinstance(exc, httpx.HTTPError):
            record.update(status="network error", reason=type(exc).__name__)
            raise WebError(f"Couldn't reach {host}: {type(exc).__name__}.") from exc
        if isinstance(exc, (httpx.InvalidURL, ValueError, UnicodeError, RecursionError)):
            # Addresses and responses that the parsers reject, reported rather than crashing.
            record.update(status="refused or failed", reason=type(exc).__name__)
            raise WebError(f"Kiki couldn't use that address or response ({type(exc).__name__}).") from exc
        raise
    finally:
        done.set()
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
    final_host = (urlsplit(got.url).hostname or "").casefold()
    if final_host != (urlsplit(target).hostname or "").casefold():
        # Redirected to another site: credit the site that actually answered,
        # not the address typed (an open redirect on a trusted domain could
        # otherwise lend its name to anything, audit A21).
        note = f"Redirected from {urlsplit(requested).hostname} to {final_host}." + (f" {note}" if note else "")
        requested = got.url
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
                raise WebError(f"That page doesn't exist (404): {_redacted(requested)}")
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
            # Server text is cleaned before any message can show it (audit L3).
            media = _INVISIBLE.sub("", response.headers.get("content-type", "")).split(";", 1)[0]
            media = media.strip().casefold()[:100]
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
    charset = safe_charset(charset)
    if media in _HTML_TYPES:
        if len(data) > IN_PROCESS_HTML_BYTES:
            # Large pages are parsed in a limited child process: crafted HTML
            # can make Python 3.12's parser run for hours (audit A5).
            try:
                title, paragraphs, headings = parse_html_isolated(
                    data, charset, main_only=True, skip_hidden=True)
            except ExtractionError as exc:
                raise WebError(f"Kiki stopped reading this page: it {exc}.") from exc
        else:
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
        text = data.decode(charset or "utf-8", errors="replace")
        lines = [_INVISIBLE.sub("", line) for line in text.splitlines()]
        blocks = [(number, line.rstrip()) for number, line in enumerate(lines, start=1)
                  if line.strip()]
        sections = _text_sections(lines)
        title = None
        kind = "line"
    if not blocks:
        raise WebError("The page has no readable text. It may build its content with JavaScript, "
                       "which Kiki doesn't run.")
    # Every source of the title is cleaned, including the fallback taken from
    # the address, which a redirect controls ("%1b%5d52;..." was printed raw;
    # re-audit).
    title = next((cleaned for candidate in (title, fallback_title, urlsplit(requested).hostname, requested)
                  if (cleaned := _INVISIBLE.sub("", candidate or "").strip()[:200])), "page")
    return WebPage(
        url=requested,
        fetched_from=fetched_from,
        title=title,
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


# A path segment that looks like a key: long, letters and digits mixed, no dots
# (Slack webhooks, bot tokens, signed share links).
_TOKEN_SEGMENT = re.compile(
    r"^(?=[^.]*\d)(?=[^.]*[A-Za-z])[A-Za-z0-9_:-]{20,}$"
    # A JWT (dots between its parts) and base64 with + / = or their %-escapes,
    # which the pattern above missed (re-audit).
    r"|^eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}(?:\.[A-Za-z0-9_-]*)?$"
    r"|^(?=.*\d)(?=.*[a-z])(?=.*[A-Z])(?=.*(?:%2[BbFf]|%3[Dd]|[+=]))(?:[A-Za-z0-9+/=_-]|%2[BbFf]|%3[Dd]){20,}$"
)


def _secret_value(name: str, value: str) -> bool:
    """A query parameter to hide: a secret-sounding name, or a value that looks
    like a random token whatever it is called."""
    return bool(_SECRET_PARAMETER.search(name) or _TOKEN_SEGMENT.match(value))


def secret_parameters(url: str) -> list[str]:
    """Where the address seems to carry a password or token: query names, the
    fragment, or a key-like path segment."""
    parts = urlsplit(url)
    found = [name for name, value in parse_qsl(parts.query, keep_blank_values=True)
             if _secret_value(name, value)]
    if any(_SECRET_PARAMETER.search(name) for name, _ in parse_qsl(parts.fragment, keep_blank_values=True)):
        found.append("#fragment")
    if any(_TOKEN_SEGMENT.match(segment) for segment in parts.path.split("/")):
        found.append("a key-like part of the path")
    return found


def _redacted(url: str) -> str:
    """The address with secret-looking values replaced, for the log and messages."""
    parts = urlsplit(url)
    path = "/".join("REDACTED" if _TOKEN_SEGMENT.match(segment) else segment
                    for segment in parts.path.split("/"))
    query = urlencode([(name, "REDACTED" if _secret_value(name, value) else value)
                       for name, value in parse_qsl(parts.query, keep_blank_values=True)])
    # Fragments never reach the server, so a logged one is only a leak.
    return parts._replace(path=path, query=query if parts.query else "",
                          fragment="REDACTED" if parts.fragment else "").geturl()


def _redacted_text(text: str) -> str:
    """Text with every address in it redacted."""
    return re.sub(r"https?://\S+", lambda match: _redacted(match.group()), text)


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
    piece: int = 0  # numbered when several passages share one span


_PASSAGE_CACHE: dict[tuple[str, int], list[_Passage]] = {}


def page_passages(page: WebPage, size: int = PASSAGE_CHARACTERS) -> list[_Passage]:
    """The page's passages, worked out once per page and reused by follow-up
    questions (a 5 MB page took seconds to split each time, audit L6)."""
    key = (page.source_id, size)
    if key not in _PASSAGE_CACHE:
        if len(_PASSAGE_CACHE) >= 4:
            _PASSAGE_CACHE.pop(next(iter(_PASSAGE_CACHE)))
        _PASSAGE_CACHE[key] = _build_passages(page, size)
    return list(_PASSAGE_CACHE[key])


def _build_passages(page: WebPage, size: int) -> list[_Passage]:
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
    # Pieces of one long paragraph share a span; number them so each passage
    # has its own citation ID (audit A9).
    seen: Counter[tuple[int, int]] = Counter()
    numbered = []
    for passage in passages:
        span = (passage.start, passage.end)
        numbered.append(replace(passage, piece=seen[span]))
        seen[span] += 1
    return numbered


def _split_long(text: str, size: int) -> list[str]:
    pieces: list[str] = []
    current = ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if len(sentence) > size:
            # Cut by index: re-slicing the remainder copied it each time, so a
            # 5 MB unpunctuated paragraph took seconds (audit L6).
            cut = len(sentence) - len(sentence) % size or len(sentence) - size
            pieces.extend(sentence[start:start + size] for start in range(0, cut, size))
            sentence = sentence[cut:]
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
            piece=passage.piece,
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
