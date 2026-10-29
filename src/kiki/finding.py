"""Whole-file finding: "I can't find the file about X".

Ranks every catalogued file (readable or not) by which query words its name,
title, folders, type, and extracted contents explain, weighted by how rare each
word is. Read-only: nothing here opens, moves, or changes a file.
"""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .retrieval import TextIndex, _STOP_WORDS

# How strongly a word hitting each field points at a file.
FIELD_WEIGHTS = {"name": 1.0, "title": 0.9, "folder": 0.8, "type": 0.7, "contents": 0.6}

# Words people use to ask for a file that say nothing about which file.
_FIND_STOP_WORDS = _STOP_WORDS | {
    "about", "any", "can", "cannot", "cant", "doc", "document", "documents", "file",
    "files", "find", "folder", "folders", "get", "had", "i", "im", "looking", "me",
    "mine", "my", "named", "called", "need", "remember", "some", "something", "think",
    "there", "thing", "was", "where", "which", "one", "saved", "somewhere", "t",
}

_TYPE_WORDS = {
    "pdf": {".pdf"}, "pdfs": {".pdf"},
    "spreadsheet": {".xlsx", ".xls", ".csv", ".ods"},
    "spreadsheets": {".xlsx", ".xls", ".csv", ".ods"},
    "excel": {".xlsx", ".xls"}, "csv": {".csv"},
    "word": {".docx", ".doc"}, "docx": {".docx"},
    "photo": {".jpg", ".jpeg", ".png", ".heic", ".gif", ".webp"},
    "photos": {".jpg", ".jpeg", ".png", ".heic", ".gif", ".webp"},
    "picture": {".jpg", ".jpeg", ".png", ".heic", ".gif", ".webp"},
    "image": {".jpg", ".jpeg", ".png", ".heic", ".gif", ".webp", ".svg"},
    "screenshot": {".png", ".jpg"},
    "slides": {".pptx", ".ppt", ".key"}, "presentation": {".pptx", ".ppt", ".key"},
    "notes": {".md", ".txt"}, "markdown": {".md"}, "text": {".txt", ".md"},
    "zip": {".zip", ".7z", ".rar"}, "archive": {".zip", ".7z", ".rar", ".tar", ".gz"},
    "video": {".mp4", ".mov", ".mkv", ".avi"}, "audio": {".mp3", ".wav", ".m4a", ".flac"},
    "recording": {".mp3", ".wav", ".m4a", ".mp4"},
    "script": {".py", ".ps1", ".sh", ".js"}, "python": {".py"},
}

_SIZE_UNITS = {"b": 1, "kb": 1024, "mb": 1024**2, "gb": 1024**3}


class FindError(ValueError):
    """A /find query or filter the user needs to fix."""


@dataclass(frozen=True)
class FindFilters:
    extensions: frozenset[str] = frozenset()
    folder: str | None = None
    name: str | None = None
    after_ns: int | None = None
    before_ns: int | None = None
    larger: int | None = None
    smaller: int | None = None

    def describe(self) -> list[str]:
        parts: list[str] = []
        if self.extensions:
            parts.append("type " + ", ".join(sorted(self.extensions)))
        if self.folder:
            parts.append(f"in folder '{self.folder}'")
        if self.name:
            parts.append(f"name contains '{self.name}'")
        if self.after_ns is not None:
            parts.append(f"modified after {_date(self.after_ns)}")
        if self.before_ns is not None:
            parts.append(f"modified before {_date(self.before_ns)}")
        if self.larger is not None:
            parts.append(f"larger than {format_size(self.larger)}")
        if self.smaller is not None:
            parts.append(f"smaller than {format_size(self.smaller)}")
        return parts

    def accepts(self, entry: dict[str, Any], folder_text: str) -> bool:
        if self.extensions and entry["extension"] not in self.extensions:
            return False
        if self.folder and self.folder.casefold() not in folder_text.casefold():
            return False
        if self.name and self.name.casefold() not in entry["name"].casefold():
            return False
        if self.after_ns is not None and entry["modified_ns"] < self.after_ns:
            return False
        if self.before_ns is not None and entry["modified_ns"] >= self.before_ns:
            return False
        if self.larger is not None and entry["size"] <= self.larger:
            return False
        if self.smaller is not None and entry["size"] >= self.smaller:
            return False
        return True


@dataclass
class FileCandidate:
    number: int
    path: str
    name: str
    folder: str
    size: int
    modified: str
    searchable: bool
    confidence: str
    reasons: dict[str, list[str]]
    score: float
    title: str | None = None
    changed_since_indexing: bool = False

    @property
    def explanation(self) -> str:
        return "; ".join(f"{place}: {', '.join(words)}" for place, words in self.reasons.items())

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "explanation": self.explanation}


@dataclass
class FindResult:
    query: str
    words: list[str]
    filters: list[str]
    candidates: list[FileCandidate] = field(default_factory=list)
    missing_skipped: int = 0
    catalogued: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "candidates": [c.to_dict() for c in self.candidates]}


def parse_query(text: str, *, now: datetime | None = None) -> tuple[str, FindFilters]:
    """Split `budget ext:xlsx after:2026-03` into words and filters."""
    now = now or datetime.now(UTC)
    words: list[str] = []
    options: dict[str, Any] = {}
    extensions: set[str] = set()
    for part in text.split():
        key, colon, value = part.partition(":")
        key = key.casefold()
        if not colon or not value or key not in {
            "ext", "type", "in", "name", "after", "since", "before", "larger", "smaller"
        }:
            words.append(part)
            continue
        if key in {"ext", "type"}:
            extensions.update(
                "." + item.lstrip(".").casefold() for item in value.split(",") if item.strip(".")
            )
        elif key in {"in", "name"}:
            options["folder" if key == "in" else "name"] = value.strip("\"'")
        elif key in {"after", "since", "before"}:
            moment = int(_parse_date(value, now).timestamp() * 1_000_000_000)
            options["before_ns" if key == "before" else "after_ns"] = moment
        else:
            options[key] = _parse_size(value)
    return " ".join(words), FindFilters(extensions=frozenset(extensions), **options)


def _parse_date(value: str, now: datetime) -> datetime:
    relative = re.fullmatch(r"(\d+)([dwmy])", value.casefold())
    if relative:
        amount, unit = int(relative.group(1)), relative.group(2)
        days = amount * {"d": 1, "w": 7, "m": 30, "y": 365}[unit]
        return now - timedelta(days=days)
    for pattern in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(value, pattern).replace(tzinfo=UTC)
        except ValueError:
            continue
    raise FindError(
        f"Could not read the date {value!r}. Use 2026, 2026-03, 2026-03-15, or 7d, 4w, 6m, 1y."
    )


def _parse_size(value: str) -> int:
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(b|kb|mb|gb)?", value.casefold())
    if not match:
        raise FindError(f"Could not read the size {value!r}. Use a number such as 500KB or 10MB.")
    return int(float(match.group(1)) * _SIZE_UNITS[match.group(2) or "b"])


def query_words(text: str) -> list[str]:
    raw = [token.casefold() for token in re.findall(r"\w+", text.replace("_", " "))]
    useful = [token for token in raw if token not in _FIND_STOP_WORDS and (len(token) > 1 or token.isdigit())]
    return list(dict.fromkeys(useful))


def _stem(word: str) -> str:
    for suffix, replacement in (("ies", "y"), ("ing", ""), ("ed", ""), ("es", ""), ("s", "")):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)] + replacement
    return word


def _split_words(text: str) -> list[str]:
    """Words in a file or folder name: `KestrelBudget_March-2026` -> kestrel,
    budget, march, 2026."""
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])", " ", text)
    return [word.casefold() for word in re.split(r"[\W_]+", spaced) if word]


def _hits(word: str, words: list[str]) -> bool:
    stem = _stem(word)
    for candidate in words:
        if candidate == word or _stem(candidate) == stem:
            return True
        # Prefixes catch "invoice" in "invoices2024" style names and short forms
        # like "tax" -> "taxes"; four letters keeps "car" out of "cards".
        if len(word) >= 4 and (candidate.startswith(word) or (len(candidate) >= 4 and word.startswith(candidate))):
            return True
    return False


class FileFinder:
    def __init__(self, index: TextIndex) -> None:
        self.index = index

    def find(self, text: str, limit: int = 3, *, now: datetime | None = None) -> FindResult:
        if not 1 <= limit <= 20:
            raise FindError("Limit must be between 1 and 20")
        words_text, filters = parse_query(text, now=now)
        words = query_words(words_text)
        if not words and filters == FindFilters():
            raise FindError("Describe the file, for example: /find budget spreadsheet march")
        entries = self.index.catalog_entries()
        result = FindResult(query=text, words=words, filters=filters.describe(), catalogued=len(entries))
        if not entries:
            return result

        prepared = []
        for entry in entries:
            folder = _relative_folder(entry["path"], entry["root"])
            if not filters.accepts(entry, folder):
                continue
            prepared.append((entry, folder))

        contents = self.index.content_matches(words) if words else {}
        places = {
            entry["path"]: [_best_field(word, entry, folder, contents) for word in words]
            for entry, folder in prepared
        }
        # Inverse document frequency: a word most files share says little
        # about which file is meant.
        rarity = {
            word: math.log(1 + len(prepared) / (1 + sum(
                1 for found in places.values() if found[position]
            )))
            for position, word in enumerate(words)
        }
        total = sum(rarity.values()) or 1.0
        scored = []
        for entry, folder in prepared:
            reasons: dict[str, list[str]] = {}
            score = explained = named = relevance = 0.0
            for word, place in zip(words, places[entry["path"]]):
                if place is None:
                    continue
                reasons.setdefault(place, []).append(word)
                score += rarity[word] * FIELD_WEIGHTS[place]
                explained += rarity[word]
                if place in {"name", "title", "folder"}:
                    named += rarity[word]
                relevance += contents.get(word, {}).get(entry["path"], 0.0)
            if words and not reasons:
                continue
            scored.append((score / total, explained / total, named / total,
                           relevance, entry, folder, reasons))

        scored.sort(key=lambda item: (item[0], item[3], item[4]["modified_ns"]), reverse=True)
        coverage: list[tuple[float, float]] = []
        # One extra candidate, so the last one shown can be compared with the next.
        for score, explained, named, _, entry, folder, reasons in scored:
            if len(result.candidates) == limit + 1:
                break
            path = Path(entry["path"])
            try:
                stat = path.stat()
            except OSError:
                result.missing_skipped += 1
                continue
            if not path.is_file():
                result.missing_skipped += 1
                continue
            result.candidates.append(FileCandidate(
                number=len(result.candidates) + 1,
                path=str(path),
                name=entry["name"],
                folder=folder or ".",
                size=stat.st_size,
                modified=_date(stat.st_mtime_ns),
                searchable=bool(entry["searchable"]),
                confidence="",
                reasons=reasons,
                score=round(score, 3),
                title=entry["title"],
                changed_since_indexing=(
                    stat.st_mtime_ns != entry["modified_ns"] or stat.st_size != entry["size"]
                ),
            ))
            coverage.append((explained, named))
        _label(result.candidates, coverage, bool(words))
        del result.candidates[limit:]
        return result



def _best_field(
    word: str, entry: dict[str, Any], folder: str, contents: dict[str, dict[str, float]]
) -> str | None:
    """The strongest place a query word appears for this file, if any."""
    if _hits(word, _split_words(Path(entry["name"]).stem)):
        return "name"
    if entry["title"] and _hits(word, _split_words(entry["title"])):
        return "title"
    if folder and _hits(word, _split_words(folder)):
        return "folder"
    if entry["extension"] in _TYPE_WORDS.get(word, set()) or entry["extension"] == f".{word}":
        return "type"
    if entry["path"] in contents.get(word, {}):
        return "contents"
    return None


_LEVELS = ("Weak match", "Possible", "Likely")


def _label(
    candidates: list[FileCandidate], coverage: list[tuple[float, float]], has_words: bool
) -> None:
    """Confidence describes the list, not each file alone.

    Only the first candidate can be Likely, and only when it explains nearly
    the whole question, mostly through its name, title, or folder (contents
    alone match too many files), and clearly leads the next candidate. Labels
    never rise further down the list.
    """
    ceiling = len(_LEVELS) - 1
    for position, (candidate, (explained, named)) in enumerate(zip(candidates, coverage)):
        if not has_words:
            candidate.confidence = "Matches filters"
            continue
        level = 1 if explained >= 0.5 else 0
        if position == 0 and explained >= 0.85 and named >= 0.5:
            runner_up = candidates[1].score if len(candidates) > 1 else 0.0
            if candidate.score - runner_up >= 0.1:
                level = 2
        ceiling = min(ceiling, level)
        candidate.confidence = _LEVELS[ceiling]


def _relative_folder(path: str, root: str) -> str:
    try:
        relative = Path(path).parent.relative_to(root)
    except ValueError:
        return str(Path(path).parent)
    return "" if str(relative) == "." else str(relative)


def _date(ns: int) -> str:
    return datetime.fromtimestamp(ns / 1_000_000_000, UTC).astimezone().strftime("%Y-%m-%d")


def format_size(size: int) -> str:
    for unit, factor in (("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)):
        if size >= factor:
            return f"{size / factor:.1f} {unit}"
    return f"{size} B"
