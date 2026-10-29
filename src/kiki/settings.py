"""Retrieval settings shared by the CLI, terminal, evaluations, and diagnostics.

Values come from defaults, then `KIKI_RAG_*` environment variables, then explicit
overrides (CLI flags). Defaults reproduce the pipeline measured in
docs/ENGINEERING_LOG.md so historical evaluations stay comparable.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields, replace
from typing import Any

# grader: the answer model grades passages 0-3 (default, measured baseline).
# qwen3-reranker: dedicated Qwen3-Reranker-0.6B served by Ollama (feature flag).
RERANKERS = ("grader", "qwen3-reranker", "none")

DEFAULT_GENERATION_MODEL = "qwen3:4b-instruct"
# Community GGUF conversion of Qwen/Qwen3-Reranker-0.6B (Apache-2.0); fidelity
# checks are recorded in docs/ENGINEERING_LOG.md.
DEFAULT_QWEN3_RERANKER = "dengcao/Qwen3-Reranker-0.6B:Q8_0"

_MODEL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-/]*(?::[A-Za-z0-9._\-]+)?$")

_ENVIRONMENT = {
    "candidates": "KIKI_RAG_CANDIDATES",
    "passages": "KIKI_RAG_PASSAGES",
    "reranker": "KIKI_RAG_RERANKER",
    "rerank_model": "KIKI_RAG_RERANK_MODEL",
    "rerank_batch_size": "KIKI_RAG_RERANK_BATCH",
    "rerank_timeout": "KIKI_RAG_RERANK_TIMEOUT",
    "context_characters": "KIKI_RAG_CONTEXT_CHARACTERS",
    "recovery": "KIKI_RAG_RECOVERY",
}


class SettingsError(ValueError):
    """A retrieval setting is invalid; the message names the setting and its range."""


@dataclass(frozen=True)
class RetrievalSettings:
    # First-stage pool handed to the reranker (fused lexical + semantic).
    candidates: int = 20
    # Passages given to the answer model (8 chosen in stage 3; was 5).
    passages: int = 8
    # grader | qwen3-reranker | none (fused order); see RERANKERS.
    reranker: str = "grader"
    # Empty means the answer model for grader, DEFAULT_QWEN3_RERANKER otherwise.
    rerank_model: str = ""
    # Upper bound on concurrent scoring requests (used by batch-capable rerankers).
    rerank_batch_size: int = 4
    # Seconds per scoring request before falling back to fused order.
    rerank_timeout: float = 90.0
    # Characters of evidence shown to the answer model across all passages.
    context_characters: int = 7_000
    # One bounded rewritten-query retry when the best reranked passage is weak.
    recovery: bool = False

    def __post_init__(self) -> None:
        _check_range("candidates", self.candidates, 1, 100)
        _check_range("passages", self.passages, 1, 20)
        if self.passages > self.candidates:
            raise SettingsError(
                f"passages ({self.passages}) cannot exceed candidates ({self.candidates})"
            )
        if self.reranker not in RERANKERS:
            raise SettingsError(
                f"reranker must be one of {', '.join(RERANKERS)}; got {self.reranker!r}"
            )
        if self.rerank_model and not _MODEL_NAME.match(self.rerank_model):
            raise SettingsError(f"rerank_model is not a valid model name: {self.rerank_model!r}")
        _check_range("rerank_batch_size", self.rerank_batch_size, 1, 16)
        _check_range("rerank_timeout", self.rerank_timeout, 1, 600)
        _check_range("context_characters", self.context_characters, 1_000, 24_000)

    @property
    def rerank_enabled(self) -> bool:
        return self.reranker != "none"

    def resolved_rerank_model(self, generation_model: str = DEFAULT_GENERATION_MODEL) -> str | None:
        if self.reranker == "none":
            return None
        if self.rerank_model:
            return self.rerank_model
        return generation_model if self.reranker == "grader" else DEFAULT_QWEN3_RERANKER

    def with_overrides(self, **overrides: Any) -> RetrievalSettings:
        values = {key: value for key, value in overrides.items() if value is not None}
        unknown = set(values) - {field.name for field in fields(self)}
        if unknown:
            raise SettingsError(f"Unknown retrieval setting(s): {', '.join(sorted(unknown))}")
        return replace(self, **values)

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> RetrievalSettings:
        environ = os.environ if environ is None else environ
        values: dict[str, Any] = {}
        for field in fields(cls):
            raw = environ.get(_ENVIRONMENT[field.name], "").strip()
            if not raw:
                continue
            values[field.name] = _parse(field.name, raw, field.type)
        return cls(**values)

    def describe(self, generation_model: str = DEFAULT_GENERATION_MODEL) -> dict[str, Any]:
        return {**asdict(self), "rerank_model": self.resolved_rerank_model(generation_model)}


def _check_range(name: str, value: float, low: float, high: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SettingsError(f"{name} must be a number; got {value!r}")
    if not low <= value <= high:
        raise SettingsError(f"{name} must be between {low} and {high}; got {value}")


def _parse(name: str, raw: str, kind: Any) -> Any:
    variable = _ENVIRONMENT[name]
    kind = str(kind)
    try:
        if kind == "int":
            return int(raw)
        if kind == "float":
            return float(raw)
    except ValueError as exc:
        raise SettingsError(f"{variable} must be a number; got {raw!r}") from exc
    if kind == "bool":
        lowered = raw.casefold()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
        raise SettingsError(f"{variable} must be on or off; got {raw!r}")
    return raw
