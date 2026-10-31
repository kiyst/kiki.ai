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


_LANGUAGES = (
    r"(?:python|javascript|typescript|js|ts|sql|regex|regexp|bash|shell script|powershell|json|yaml|"
    r"html|css|java|rust|golang|kotlin|swift|php|ruby|lua|(?<!\w)c\+\+|(?<!\w)c#)"
)
_CODE = re.compile(
    r"```|\b(?:leetcode|algorithm|time complexity|space complexity|debug|refactor|"
    r"stack trace|traceback|unit tests?|pytest|code review|"
    r"implement(?:ation)?|syntax error)\b"
    # "Review this Python: ..." and "fix this SQL query" (the plan's routing
    # regression); a language name alone, like "a python at the zoo", is chat.
    r"|\b(?:review|fix|debug|explain|optimi[sz]e|rewrite|convert|translate|write|clean\s+up|"
    r"check|improve|test|compute|solve|code|build|create|make)\b[^.?!\n]{0,40}?" + _LANGUAGES + r"(?![\w+#])"
    # Code itself, pasted into the message.
    r"|\bdef\s+\w+\s*\(|^\s*class\s+\w+[\s(:{]|\bfunction\s*\w*\s*\(|#include\s*<|console\.log\(|"
    r"\bpublic\s+static\s+void\b|\bSELECT\b[\s\S]{1,200}?\bFROM\b|\b\w+(?:Error|Exception):"
    # "class" and "function" alone also mean school and biology, which stay
    # with the personality model; in code talk they come with a code word.
    r"|\b(?:my|this|the|a|that)\s+(?:python\s+|js\s+)?(?:function|method|class)\s+"
    r"(?:returns?|throws?|crashes|fails|raises|takes|is\s+(?:returning|throwing|undefined|null|none))\b",
    re.IGNORECASE | re.MULTILINE,
)
_RAG = re.compile(
    r"\b(?:indexed|corpus|documents?|sources?|pdfs?|search (?:my|the) files?)\b",
    re.IGNORECASE,
)
_WEATHER = re.compile(r"\b(?:weather|forecast|temperature)\b", re.IGNORECASE)
_MEMORY = re.compile(
    r"^\s*(?:please\s+)?(?:remember|forget|what do you remember)\b", re.IGNORECASE
)


# A question that refers back to the previous turn ("why did that happen",
# "explain why that fix works"). After a code answer it stays with the code
# model; thanks, banter, and questions about anything else go back to Kiki.
_FOLLOW_UP = re.compile(
    r"^\s*(?:ok(?:ay)?[,\s]+|so[,\s]+|but[,\s]+|wait[,\s]+)?"
    r"(?:why|how|what|explain|does|did|is|can|could|should|would|where|which|when)\b",
    re.IGNORECASE,
)
_REFERS_BACK = re.compile(
    r"\b(?:that|it|this|those|these|the (?:fix|code|bug|error|loop|function|query|change|regex|line))\b",
    re.IGNORECASE,
)
_SMALL_TALK = re.compile(
    r"^\s*(?:thanks|thank you|ty|thx|lol|lmao|haha|nice|cool|great|perfect|awesome)\b", re.IGNORECASE
)


def technical_follow_up(prompt: str) -> bool:
    """A question about the previous (technical) answer rather than new small talk."""
    return bool(
        _FOLLOW_UP.search(prompt)
        and _REFERS_BACK.search(prompt)
        and not _SMALL_TALK.search(prompt)
        and not re.search(r"\b(?:you|your|yourself|kiki)\b", prompt, re.IGNORECASE)
    )


def route_prompt(prompt: str, *, mode: str = "chat", after_code: bool = False) -> Route:
    """Classify a turn without granting permission or executing anything.

    after_code: the previous turn in this mode was answered as code, so a
    question referring back to it stays with the code model.
    """
    if _WEATHER.search(prompt):
        return Route(Capability.WEATHER, "explicit live-weather language")
    if _MEMORY.search(prompt):
        return Route(Capability.MEMORY, "explicit memory request")
    if mode == "rag" or _RAG.search(prompt):
        return Route(Capability.RAG, "RAG mode or document-search language")
    if _CODE.search(prompt):
        return Route(Capability.CODE, "code or algorithm language")
    if after_code and technical_follow_up(prompt):
        return Route(Capability.CODE, "follow-up to a code answer")
    return Route(Capability.CHAT, "ordinary conversation")
