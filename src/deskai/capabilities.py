from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class Capability(StrEnum):
    CHAT = "chat"
    CODE = "code"
    RAG = "rag"
    WEATHER = "weather"
    MEMORY = "memory"


@dataclass(frozen=True)
class Route:
    capability: Capability
    reason: str


_CODE = re.compile(
    r"```|\b(?:leetcode|algorithm|time complexity|space complexity|debug|refactor|"
    r"stack trace|traceback|unit tests?|pytest|function|class|code review|"
    r"implement(?:ation)?|syntax error)\b",
    re.IGNORECASE,
)
_RAG = re.compile(
    r"\b(?:indexed|corpus|documents?|sources?|pdfs?|search (?:my|the) files?)\b",
    re.IGNORECASE,
)
_WEATHER = re.compile(r"\b(?:weather|forecast|temperature)\b", re.IGNORECASE)
_MEMORY = re.compile(
    r"^\s*(?:please\s+)?(?:remember|forget|what do you remember)\b", re.IGNORECASE
)


def route_prompt(prompt: str, *, mode: str = "chat") -> Route:
    """Classify a turn without granting permission or executing anything."""
    if _WEATHER.search(prompt):
        return Route(Capability.WEATHER, "explicit live-weather language")
    if _MEMORY.search(prompt):
        return Route(Capability.MEMORY, "explicit memory request")
    if mode == "rag" or _RAG.search(prompt):
        return Route(Capability.RAG, "RAG mode or document-search language")
    if _CODE.search(prompt):
        return Route(Capability.CODE, "code or algorithm language")
    return Route(Capability.CHAT, "ordinary conversation")
