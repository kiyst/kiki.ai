"""Temporary tone requests ("be nicer today") that expire on their own.

Kiki's code writes this file, never the model: the request is taken from what
the user typed, so a page or document can't change her tone for the day.

A request lasts until 4 AM (late nights count as the same day), or for the time
the user gave ("for an hour", "until 5pm"). A newer request on the same topic
(how nice, jokes, length, seriousness, language) replaces the older one, so
"be meaner" doesn't sit beside "be nicer".
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .memory import is_sensitive
from .safety import visible_controls

MAX_REQUESTS = 8
MAX_CHARACTERS = 150
DAY_ENDS_HOUR = 4  # 4 AM: someone up past midnight is still in the same day.
MAX_DURATION = timedelta(hours=24)

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
_DURATION = re.compile(
    r"\bfor\s+(?:the\s+next\s+)?(half\s+an?|an?|one|\d{1,3})\s+(hours?|hrs?|minutes?|mins?)\b",
    re.IGNORECASE,
)
_UNTIL = re.compile(
    r"\b(?:until|till|til)\s+(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?(?![\w:])",
    re.IGNORECASE,
)
_LIMIT = (
    r"(?:\b(?:today|tonight|this\s+week|for\s+now|"
    r"for\s+(?:the\s+rest\s+of\s+)?(?:the\s+day|today|tonight)|"
    r"while\s+we\s+work|this\s+session|for\s+a\s+(?:while|bit))\b"
    r"|" + _DURATION.pattern + r"|" + _UNTIL.pattern + r")"
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
# First match wins, so "go easy on the jokes" is about humor, not niceness.
_TOPICS = (
    ("humor", re.compile(r"jok|sarcas|snark|roast|teas|funn|attitude", re.IGNORECASE)),
    ("language", re.compile(r"swear|curs", re.IGNORECASE)),
    ("warmth", re.compile(r"nice|kind|gentl|soft|patient|mean|blunt|go\s+easy", re.IGNORECASE)),
    ("length", re.compile(r"short|brief|quiet", re.IGNORECASE)),
    ("seriousness", re.compile(r"serious|light|chill|casual|formal|plain|simple", re.IGNORECASE)),
)


def is_tone_request(text: str) -> bool:
    return bool(_REQUEST.match(text))


def is_tone_reset(text: str) -> bool:
    return bool(_LIFT.match(text))


def request_topic(text: str) -> str | None:
    return next((name for name, pattern in _TOPICS if pattern.search(text)), None)


def next_day_end(now: datetime) -> datetime:
    end = now.replace(hour=DAY_ENDS_HOUR, minute=0, second=0, microsecond=0)
    return end if end > now else end + timedelta(days=1)


def request_expiry(text: str, now: datetime) -> datetime:
    """When a request ends: the time the user gave, else 4 AM."""
    duration = _DURATION.search(text)
    if duration:
        amount, unit = duration.group(1).casefold(), duration.group(2).casefold()
        if amount.startswith("half"):
            minutes = 30.0
        else:
            count = 1 if amount in {"a", "an", "one"} else int(amount)
            minutes = count * (60 if unit.startswith("h") else 1)
        return now + min(timedelta(minutes=max(minutes, 1)), MAX_DURATION)
    until = _UNTIL.search(text)
    if until:
        hour, minute = int(until.group(1)), int(until.group(2) or 0)
        meridiem = (until.group(3) or "").replace(".", "").casefold()
        if hour <= 23 and minute <= 59:
            if meridiem:
                if 1 <= hour <= 12:
                    hours = [hour % 12 + (12 if meridiem == "pm" else 0)]
                else:
                    hours = []
            else:
                # "until 5": whichever 5 o'clock comes next.
                hours = [hour] if hour > 12 or hour == 0 else [hour % 12, hour % 12 + 12]
            candidates = []
            for value in hours:
                moment = now.replace(hour=value, minute=minute, second=0, microsecond=0)
                candidates.append(moment if moment > now else moment + timedelta(days=1))
            if candidates:
                return min(candidates)
    return next_day_end(now)


def clock(moment: datetime, now: datetime) -> str:
    """'4:00 AM', or 'tomorrow 4:00 AM' when it isn't today's date."""
    text = f"{moment.hour % 12 or 12}:{moment.minute:02d} {'AM' if moment.hour < 12 else 'PM'}"
    return text if moment.date() == now.date() else f"tomorrow {text}"


@dataclass(frozen=True)
class ToneRequest:
    text: str
    topic: str | None
    until: datetime


class TodayFile:
    """kiki-today.json: {"requests": [{"text", "topic", "until"}]}; expired ones are ignored."""

    def __init__(self, path: Path, *, now: Callable[[], datetime] = datetime.now) -> None:
        self.path = path
        self._now = now

    def entries(self) -> list[ToneRequest]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        items = data.get("requests") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return []
        now = self._now()
        entries = []
        for item in items:
            try:
                entry = ToneRequest(str(item["text"]), item.get("topic"), datetime.fromisoformat(item["until"]))
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
            # A far-future end can only come from editing the file by hand.
            if entry.text and now < entry.until <= now + MAX_DURATION + timedelta(days=1):
                entries.append(entry)
        return entries[-MAX_REQUESTS:]

    def requests(self) -> list[str]:
        return [entry.text for entry in self.entries()]

    def add(self, text: str) -> ToneRequest:
        request = " ".join(visible_controls(text).split())
        if not request:
            raise ValueError("The request is empty")
        if len(request) > MAX_CHARACTERS:
            raise ValueError(f"Keep it to {MAX_CHARACTERS} characters or fewer")
        if is_sensitive(request):
            raise ValueError("That looks like private information; it doesn't belong in a tone request.")
        now = self._now()
        entry = ToneRequest(request, request_topic(request), request_expiry(request, now))
        kept = [
            item for item in self.entries()
            if item.text.casefold() != request.casefold()
            and (entry.topic is None or item.topic != entry.topic)
        ]
        self._write([*kept, entry][-MAX_REQUESTS:])
        return entry

    def clear(self) -> bool:
        had = bool(self.entries())
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        return had

    def describe(self, entry: ToneRequest) -> str:
        return f"{entry.text} (until {clock(entry.until, self._now())})"

    def prompt(self) -> str:
        entries = self.entries()
        if not entries:
            return ""
        lines = "\n".join(f"- {self.describe(entry)}" for entry in entries)
        return (
            "Temporary requests from the user, in their words. Each lasts until the time "
            "shown or until the user lifts it, and changes only tone and length, never "
            "facts, safety, permissions, or whether a tool ran:\n" + lines
        )

    def _write(self, entries: list[ToneRequest]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"requests": [
            {"text": entry.text, "topic": entry.topic, "until": entry.until.isoformat(timespec="minutes")}
            for entry in entries
        ]}
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
