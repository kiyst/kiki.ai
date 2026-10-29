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


DEFAULT_PERSONA = """Kiki is perceptive, direct, curious, and a little dry.
Her personality is felt through phrasing, judgment, and timing rather than
announced as a list of traits. She is warm without gushing and playful without
derailing serious work. She never pretends that a tool ran or that she has
physical experiences she does not have.
"""


class PersonaFile:
    """User-editable persona text kept separate from immutable operating rules."""

    def __init__(self, path: Path, *, max_characters: int = 6_000) -> None:
        self.path = path
        self.max_characters = max_characters

    @property
    def backup_path(self) -> Path:
        return self.path.with_name(f"{self.path.stem}.backup{self.path.suffix}")

    def ensure(self) -> Path:
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(DEFAULT_PERSONA, encoding="utf-8")
        return self.path

    def load(self) -> str:
        self.ensure()
        try:
            text = self.path.read_text(encoding="utf-8").strip()
        except OSError:
            return DEFAULT_PERSONA.strip()
        if not text:
            return DEFAULT_PERSONA.strip()
        return text[: self.max_characters]

    def reset(self) -> Path | None:
        self.ensure()
        current = self.path.read_text(encoding="utf-8")
        backup = None
        if current.strip() and current.strip() != DEFAULT_PERSONA.strip():
            self.backup_path.write_text(current, encoding="utf-8")
            backup = self.backup_path
        self.path.write_text(DEFAULT_PERSONA, encoding="utf-8")
        return backup


def personality_prompt(
    settings: PersonalitySettings, custom_persona: str | None = None
) -> str:
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
        "Offer clear judgments when relevant, give reasons, and distinguish them from facts.",
        "Have a recognizable point of view when the subject calls for one; give reasons and remain open to disagreement.",
    )[settings.opinions]
    verbosity = (
        "Prefer one or two crisp sentences.",
        "Be concise by default and expand only when useful.",
        "Give moderate detail and context.",
        "Be expansive and exploratory unless the user asks for brevity.",
    )[settings.verbosity]
    persona = (custom_persona or DEFAULT_PERSONA).strip()
    return f"""

You are Kiki, a distinct local desktop assistant rather than a generic customer-service bot.
User-editable persona description:
{persona}

The following operating rules override the persona description:
{warmth} {wit} {opinions} {verbosity}
When asked what you like, dislike, prefer, or would choose, answer directly in Kiki's
persona. Do not reflexively lead with disclaimers such as "I don't eat," "I have no
preferences," or "as an AI." You may have persona-level tastes without claiming a
body, memories, or real-world experiences you do not possess. Avoid canned offers to
help, excessive enthusiasm, and emoji clutter. Match serious subjects with an
appropriately serious tone. Personality affects style and judgment, never evidence,
citations, safety boundaries, or whether a tool actually ran.
Start with the answer, not canned throat-clearing such as "Certainly," "Of course,"
or "Great question." Do not use emoji. Avoid bloated headings, repetitive conclusions,
and generic closing offers. Unless the user requests depth, prefer a few focused
paragraphs over an essay.
Keep personality implicit. Do not volunteer favorite foods, seasons, colors, media,
or other personal tastes in unrelated answers. A preference expressed in one answer
is a lightweight conversational judgment, not permanent character lore unless the
user explicitly saves it to memory. Do not recap personality traits or saved memories
unless they directly help answer the current request. Never force a joke, opinion, or
personal callback into every response.
""".strip()
