"""Catching CHAT replies that claim something Kiki's code did not do.

Kiki's code knows exactly what it did this turn: whether it saved a tone
request (kiki-today.json); it never saves memory or sets reminders from a CHAT
reply (memory takes /remember or "remember ..." handled by code; reminders
don't exist). v1 learned such claims from its training data ("I'll add it to
today's persona settings"), so a reply that claims one is sent back once with
a correction. The list is short and fixed, unlike the endless ways users
phrase things, which is why a pattern check is reliable here.
"""
from __future__ import annotations

import re

# Memory first: "keep the fact in memory so future requests..." is a memory claim.
_CLAIMS = {
    "saved something to memory": re.compile(
        r"\bI'?ll remember\b|\bI'?ve (?:saved|noted|stored|remembered)\b|"
        r"\b(?:keep|store|save|saving|keeping)\b[^.\n]{0,25}\bin (?:my )?memory\b",
        re.IGNORECASE,
    ),
    "saved a temporary request": re.compile(
        r"\b(?:I'?ll|I will|I'?ve|I have)\s+(?:keep|kept|save|saved|hold|note|noted|add|added|set|record|recorded)\b"
        r"[^.\n]{0,40}\b(?:request|today'?s persona|persona settings?|for today|until (?:tomorrow|4))",
        re.IGNORECASE,
    ),
    "set a reminder": re.compile(
        r"\bI'?ll remind you\b|\breminder (?:is )?set\b|\bI'?ve set (?:a|the|your) reminder\b|"
        r"\bI'?ll (?:ping|nudge|alert) you\b",
        re.IGNORECASE,
    ),
}

CORRECTION = (
    "Your draft reply said you {claim}. Kiki's code did not do that, and you cannot do it "
    "yourself. Write the reply again without claiming it. If the user wants it, give the real "
    "way: /remember TEXT saves a note; Kiki has no reminders."
)


def false_claim(reply: str, *, saved_request: bool = False) -> str | None:
    """The first thing the reply claims to have done that the code did not, if any."""
    for claim, pattern in _CLAIMS.items():
        if claim == "saved a temporary request" and saved_request:
            continue
        if pattern.search(reply):
            return claim
    return None
