from __future__ import annotations

import os
from dataclasses import dataclass

from .capabilities import Capability


@dataclass(frozen=True)
class ModelSelection:
    profile: str
    model: str
    reason: str


PROFILES = ("auto", "fast", "smart", "max")


class ModelRouter:
    """Task-aware model selection with explicit, locally configurable profiles."""

    def __init__(self, default_model: str) -> None:
        self.default_model = default_model

    def models(self) -> dict[str, str]:
        return {
            "personality": os.getenv(
                "KIKI_MODEL_PERSONALITY", self.default_model
            ).strip()
            or self.default_model,
            "fast": os.getenv("KIKI_MODEL_FAST", self.default_model).strip()
            or self.default_model,
            "smart": os.getenv("KIKI_MODEL_SMART", self.default_model).strip()
            or self.default_model,
            "max": os.getenv("KIKI_MODEL_MAX", self.default_model).strip()
            or self.default_model,
        }

    def select(self, profile: str, capability: Capability) -> ModelSelection:
        profile = profile.casefold()
        if profile not in PROFILES:
            raise ValueError(f"Unknown model profile: {profile}")
        if profile == "auto":
            chosen = "smart" if capability == Capability.CODE else "personality"
            reason = f"AUTO selected {chosen.upper()} for {capability.value}"
        else:
            chosen = profile
            reason = f"User selected {profile.upper()}"
        return ModelSelection(chosen, self.models()[chosen], reason)
