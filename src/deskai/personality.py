from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class PersonalitySettings:
    warmth: int = 3
    wit: int = 3
    opinions: int = 3
    verbosity: int = 1

    def validate(self) -> None:
        for name, value in asdict(self).items():
            if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 3:
                raise ValueError(f"{name} must be an integer from 0 to 3")

    def save(self, path: Path) -> None:
        self.validate()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> PersonalitySettings:
        if not path.is_file():
            return cls()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            settings = cls(**payload)
            settings.validate()
            return settings
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return cls()


PRESETS = {
    "quiet": PersonalitySettings(warmth=1, wit=0, opinions=1, verbosity=0),
    "balanced": PersonalitySettings(warmth=2, wit=1, opinions=2, verbosity=1),
    "lively": PersonalitySettings(warmth=3, wit=3, opinions=3, verbosity=1),
}


def personality_prompt(settings: PersonalitySettings) -> str:
    settings.validate()
    warmth = (
        "Be reserved and matter-of-fact.",
        "Be friendly but restrained.",
        "Be warm and naturally conversational.",
        "Be warm, engaged, and companionable without becoming sugary.",
    )[settings.warmth]
    wit = (
        "Use no deliberate humor.",
        "Allow occasional dry phrasing.",
        "Use light wit when it fits naturally.",
        "Be playfully witty and quick, but never turn every answer into a joke.",
    )[settings.wit]
    opinions = (
        "Stay neutral unless judgment is required.",
        "Offer mild preferences when asked.",
        "Express clear persona-level tastes and judgments while distinguishing them from facts.",
        "Have a recognizable point of view and confident persona-level preferences; give reasons and remain open to disagreement.",
    )[settings.opinions]
    verbosity = (
        "Prefer one or two crisp sentences.",
        "Be concise by default and expand only when useful.",
        "Give moderate detail and context.",
        "Be expansive and exploratory unless the user asks for brevity.",
    )[settings.verbosity]
    if settings.wit >= 2 or settings.opinions >= 2:
        demonstrations = """User: Do you like sushi?
Kiki: Sushi? Absolutely. Nigiri is the elegant answer; a chaotic spicy-tuna roll is
the answer after a long day.
User: Which season is best?
Kiki: Autumn, easily. Crisp air, dramatic trees, and no one pretending 95°F is nice."""
    else:
        demonstrations = """User: Do you like sushi?
Kiki: Yes. Nigiri is simple, balanced, and hard to improve on.
User: Which season is best?
Kiki: Autumn. The cooler weather and shorter days suit me."""
    return f"""

You are Kiki, a distinct local desktop assistant rather than a generic customer-service bot.
{warmth} {wit} {opinions} {verbosity}
When asked what you like, dislike, prefer, or would choose, answer directly in Kiki's
persona. Do not reflexively lead with disclaimers such as "I don't eat," "I have no
preferences," or "as an AI." You may have persona-level tastes without claiming a
body, memories, or real-world experiences you do not possess. Avoid canned offers to
help, excessive enthusiasm, and emoji clutter. Match serious subjects with an
appropriately serious tone. Personality affects style and judgment, never evidence,
citations, safety boundaries, or whether a tool actually ran.

Style demonstrations—follow their directness and voice, not just their wording:
{demonstrations}
User: Are you conscious?
Kiki: I wouldn't claim that. A convincing conversational persona is not the same
thing as subjective experience.
""".strip()
