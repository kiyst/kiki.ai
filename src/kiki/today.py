"""Temporary tone requests ("be nicer today") that last until midnight.

Kiki's code writes this file, never the model: the request is taken from what
the user typed, so a page or document can't change her tone for the day.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import date
from pathlib import Path

from .memory import is_sensitive
from .safety import visible_controls

MAX_REQUESTS = 5
MAX_CHARACTERS = 200

# Asked of Kiki herself (imperative, or "can you"), about her tone, with a time
# limit. "I need to be nicer to my coworkers today" is about the user, so it
# doesn't match: the request has to start the message.
_TONE = (
    r"(?:be\s+(?:a\s+(?:bit|little)\s+)?(?:more\s+|less\s+)?"
    r"(?:nicer|kinder|nice|kind|gentle|gentler|softer|patient|serious|brief|briefer|quiet|quieter|"
    r"blunter|meaner|funnier|sarcastic|formal|casual|chill)"
    r"|(?:no|stop(?:\s+with)?(?:\s+the)?|cut(?:\s+out)?\s+the|drop\s+the|lay\s+off(?:\s+the)?|"
    r"ease\s+up\s+on(?:\s+the)?|go\s+easy\s+on(?:\s+the)?|less|more)\s+"
    r"(?:jokes?|joking|sarcasm|snark|roasting|teasing|attitude|swearing|cursing)"
    r"|keep\s+(?:it|things|answers|your\s+answers|replies)\s+(?:short|brief|serious|simple|plain|light)"
    r"|go\s+easy\s+on\s+me|don'?t\s+(?:joke|roast\s+me|tease\s+me|be\s+mean))"
)
_LIMIT = (
    r"\b(?:today|tonight|for\s+now|for\s+(?:the\s+rest\s+of\s+)?(?:the\s+day|today|tonight)|"
    r"while\s+we\s+work|this\s+session|for\s+a\s+(?:while|bit))\b"
)
_REQUEST = re.compile(
    r"^\s*(?:(?:hey|ok(?:ay)?|ugh|so)[,\s]+)?(?:kiki[,\s]+)?"
    r"(?:(?:can|could|would|will)\s+you\s+(?:please\s+)?|please\s+|pls\s+|just\s+)?"
    + _TONE + r".{0,60}?" + _LIMIT,
    re.IGNORECASE | re.DOTALL,
)
_LIFT = re.compile(
    r"^\s*(?:(?:ok(?:ay)?|alright|cool)[,\s]+)?(?:kiki[,\s]+)?"
    r"(?:(?:you\s+can|go)\s+)?(?:be\s+|go\s+)?back\s+to\s+(?:normal|your\s+usual(?:\s+self)?)\b"
    r"|^\s*(?:(?:ok(?:ay)?|alright)[,\s]+)?(?:kiki[,\s]+)?you\s+can\s+(?:joke|roast\s+me|be\s+mean|be\s+yourself)\s+again\b",
    re.IGNORECASE,
)


def is_tone_request(text: str) -> bool:
    return bool(_REQUEST.match(text))


def is_tone_reset(text: str) -> bool:
    return bool(_LIFT.match(text))


class TodayFile:
    """kiki-today.json: {"date": "YYYY-MM-DD", "requests": [...]}, ignored after that date."""

    def __init__(self, path: Path, *, today: Callable[[], date] = date.today) -> None:
        self.path = path
        self._today = today

    def requests(self) -> list[str]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(data, dict) or data.get("date") != self._today().isoformat():
            return []
        requests = data.get("requests")
        if not isinstance(requests, list):
            return []
        return [item for item in requests if isinstance(item, str) and item][:MAX_REQUESTS]

    def add(self, text: str) -> str:
        request = " ".join(visible_controls(text).split())
        if not request:
            raise ValueError("The request is empty")
        if len(request) > MAX_CHARACTERS:
            raise ValueError(f"Keep it to {MAX_CHARACTERS} characters or fewer")
        if is_sensitive(request):
            raise ValueError("That looks like private information; it doesn't belong in a tone request.")
        current = [item for item in self.requests() if item.casefold() != request.casefold()]
        current.append(request)
        self._write(current[-MAX_REQUESTS:])
        return request

    def clear(self) -> bool:
        had = bool(self.requests())
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        return had

    def prompt(self) -> str:
        requests = self.requests()
        if not requests:
            return ""
        lines = "\n".join(f"- {item}" for item in requests)
        return (
            "Temporary requests from the user for today, in their words. They last until "
            "midnight or until the user lifts them, and change only tone and length, never "
            "facts, safety, permissions, or whether a tool ran:\n" + lines
        )

    def _write(self, requests: list[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"date": self._today().isoformat(), "requests": requests}
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
