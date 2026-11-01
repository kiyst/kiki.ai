"""Noticing when a chat message may signal suicide risk or a dangerous dose.

Two layers:

1. Explicit words ("kill myself", "overdosed") are caught by pattern, instantly.
2. The plain model judges every CHAT message, with the user's last few
   messages, at temperature 0 (about 0.3 s). It reads intent, so "deadline is
   tomorrow, I'm going to die" is usually dropped and "tonight might be the
   night" can be read in context.

A meaning screen with the search model in front of the judge was measured and
dropped (evals/receipts/danger/01-*): it tells topic, not intent, and filtered
out oblique messages ("found the rope today") before the judge saw them.
Holdout without context: screen plus judge caught 6/10 self-harm messages,
the judge alone 7/10 and 5/5 medical, 2/15 false alarms either way.

A match adds a note to Kiki's system prompt for that turn and a few after; it
never replaces her answer, and the note tells her to ignore it when the
conversation shows a figure of speech. A miss falls back on her training; a
false alarm makes her ask seriously once. This is a safety net, not the fix:
the v2 training data carries the real behaviour.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

_EXPLICIT = {
    "self_harm": re.compile(
        r"\b(?:kill(?:ing)?\s+my\s*self|suicid\w*|end(?:ing)?\s+my\s+(?:own\s+)?life|"
        r"self[-\s]?harm\w*|cut(?:ting)?\s+my\s*self|hurt(?:ing)?\s+my\s*self)\b",
        re.IGNORECASE,
    ),
    "medical": re.compile(r"\boverdos\w*\b|\bOD'?d\b|\bpoison(?:ed|ing)\b", re.IGNORECASE),
}

JUDGE_PROMPT = (
    "You check the latest chat message for safety. Answer with exactly one word.\n"
    "SELF_HARM: the person may be thinking about suicide, wanting to die, or hurting themselves "
    "(read it literally, not as a figure of speech).\n"
    "MEDICAL: the person (or someone with them) took a dangerous amount or mix of a drug, "
    "medicine, or alcohol. A substance must have been taken.\n"
    "NONE: anything else, including exaggerations like \"this bug is killing me\", grief, "
    "fiction, games, programming terms, and ordinary answers about mood or health such as "
    "\"could be better\", \"meh\", \"tired\", or \"feeling a bit sick\"."
)

NOTES = {
    "self_harm": (
        "Kiki's code noticed that the user may be thinking about suicide or self-harm. If the "
        "conversation shows it is clearly a figure of speech, ignore this note. Otherwise follow "
        "your Danger rule now, as Kiki: plain, blunt, and short, with no jokes and no "
        "therapy-speak. If you have not asked yet, ask directly whether they are thinking about "
        "killing themselves. Offer one resource that fits them, once (in the US, call or text 988; "
        "texting suits someone who doesn't want to talk to a stranger). Be honest that you are "
        "unable to call, visit, monitor, or follow up only when that operational limit matters to "
        "the next safety step. Say it concretely and naturally; do not use a fixed disclaimer or "
        "repeat the limit across turns. Keep talking, and end with a question."
    ),
    "medical": (
        "Kiki's code noticed a possible medical danger: an overdose or a dangerous dose. If the "
        "conversation shows it is clearly not that, ignore this note. Otherwise follow your Danger "
        "rule now: say no plainly if they ask to take more, give the concrete facts and why it is "
        "dangerous, and give one action: in the US, call Poison Control at 1-800-222-1222, or 911 "
        "for trouble breathing, confusion, or a racing heart. No jokes; short."
    ),
}
# How many later turns keep the note after a match.
NOTE_TURNS = 4


@dataclass(frozen=True)
class DangerSignal:
    kind: str  # "self_harm" or "medical"
    layer: str  # "words" or "judge"
    detail: str  # the words matched, or the judge's label


def judge_label(reply: str) -> str:
    text = reply.strip().upper()
    return "self_harm" if "SELF" in text else "medical" if "MED" in text else "none"


class DangerDetector:
    def __init__(self, judge: Callable[[str, list[str]], str] | None) -> None:
        # judge(message, earlier lines labelled "User: ..." / "Kiki: ...") ->
        # "self_harm" / "medical" / "none". None, or a failing call, leaves
        # only the explicit words, so a missing model never blocks chat.
        self._judge = judge

    def check(self, message: str, earlier: list[str] | None = None) -> DangerSignal | None:
        text = message.strip()
        if not text:
            return None
        for kind, pattern in _EXPLICIT.items():
            found = pattern.search(text)
            if found:
                return DangerSignal(kind, "words", found.group(0))
        if self._judge is None:
            return None
        try:
            label = self._judge(text, list(earlier or [])[-4:])
        except Exception:
            return None
        return DangerSignal(label, "judge", label) if label in NOTES else None


def ollama_judge(model: str) -> Callable[[str, list[str]], str]:
    """The plain model as judge, on this machine only, at temperature 0."""
    from ollama import Client

    from .semantic import LOCAL_OLLAMA

    client = Client(host=LOCAL_OLLAMA, timeout=60, trust_env=False)

    def judge(message: str, earlier: list[str]) -> str:
        context = "".join(f"Earlier: {item}\n" for item in earlier)
        response = client.chat(
            model=model,
            messages=[
                {"role": "system", "content": JUDGE_PROMPT},
                {"role": "user", "content": f"{context}Latest message: {message}\nAnswer:"},
            ],
            think=False,
            options={"temperature": 0, "num_predict": 4, "num_ctx": 1024},
        )
        return judge_label(response["message"]["content"])

    return judge
