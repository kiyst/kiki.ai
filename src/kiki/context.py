"""How much of a conversation Kiki holds in mind, sized to the computer she runs on.

Applies to CHAT. Web and document answers keep the 4K baseline: at 8K they were
no better and about half again slower on an 8 GB GPU (evals/receipts/context/).
"""
from __future__ import annotations

import os

# Tokens of reading space (instructions, conversation, evidence, and the answer
# together). Measured with kiki-personality:v1 (Q4_K_M) on Ollama 0.40.12 and an
# 8 GB GTX 1080: 4K 3.2 GB, 8K 3.9 GB, 16K 5.1 GB all on the GPU; 32K 7.9 GB,
# a fifth of it spilled to the CPU.
CONTEXT_SIZES = {
    "small": 4_096,
    "standard": 8_192,
    "large": 16_384,
    "max": 32_768,
}
DEFAULT_CONTEXT = "standard"
CONTEXT_MEMORY = {"small": "3.2 GB", "standard": "3.9 GB", "large": "5.1 GB", "max": "7.9 GB"}

# Conversation kept per 4K of reading space: the original 12 messages and
# 4,000 characters, about a quarter of the space.
_MESSAGES_PER_4K = 12
_CHARACTERS_PER_4K = 4_000


def context_tokens(value: str | None = None) -> int:
    """A size name ("standard") or KIKI_CONTEXT; raises ValueError for anything else."""
    name = (os.getenv("KIKI_CONTEXT", "") if value is None else value).strip().casefold()
    name = name or DEFAULT_CONTEXT
    if name not in CONTEXT_SIZES:
        raise ValueError(f"Choose one of: {', '.join(CONTEXT_SIZES)}")
    return CONTEXT_SIZES[name]


def context_name(tokens: int) -> str:
    return next((name for name, size in CONTEXT_SIZES.items() if size == tokens), f"{tokens} tokens")


def history_limits(tokens: int) -> tuple[int, int]:
    """(messages, characters) of conversation to keep for this reading space."""
    scale = max(1, tokens // CONTEXT_SIZES["small"])
    return _MESSAGES_PER_4K * scale, _CHARACTERS_PER_4K * scale
