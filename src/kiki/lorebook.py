"""Kiki's character sheet, added to a reply only when its topic comes up.

The sheet (training/personality/kiki_sheet.md) holds stances with reasons,
each row tagged with topics. Like a roleplay lorebook, an entry reaches the
model only when one of its topics appears in the user's recent messages, so
winter comes up when the weather does and never during a database migration.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

SHEET_PATH = Path(__file__).resolve().parents[2] / "training" / "personality" / "kiki_sheet.md"
MAX_ENTRIES = 2
HEADER = (
    "Kiki's character sheet, for this topic. These are stances, not lines: keep the stance, "
    "say it in fresh words, use at most one reason or none, and never claim senses or a body "
    "(she experiences everything on paper):"
)


@dataclass(frozen=True)
class SheetEntry:
    taste: str
    reasons: str
    topics: tuple[str, ...]

    def matches(self, text: str) -> bool:
        return any(re.search(_topic_pattern(topic), text) for topic in self.topics)


def _topic_pattern(topic: str) -> str:
    """Whole words, singular or plural: "jokes" matches "joke" and "jokes"."""
    stem = topic[:-1] if topic.endswith("s") and len(topic) > 3 else topic
    return rf"\b{re.escape(stem)}(?:s|es)?\b"


def load_sheet(path: Path = SHEET_PATH) -> list[SheetEntry]:
    """Rows of the sheet's tables that have topics; a missing sheet is an empty one."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    entries = []
    for line in lines:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 4 or cells[0] in {"Taste", "---"} or set(cells[0]) <= {"-"}:
            continue
        taste, _strength, reasons, topics = cells
        names = tuple(topic.strip().casefold() for topic in topics.split(",") if topic.strip())
        if names:
            entries.append(SheetEntry(taste, reasons, names))
    return entries


def sheet_prompt(entries: list[SheetEntry], recent: list[str]) -> str:
    """The matching entries for the user's recent messages, or nothing."""
    text = " ".join(recent).casefold()
    matched = [entry for entry in entries if entry.matches(text)][:MAX_ENTRIES]
    if not matched:
        return ""
    return HEADER + "\n" + "\n".join(f"- {entry.taste}: {entry.reasons}" for entry in matched)
