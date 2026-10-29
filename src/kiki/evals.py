from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .model_client import ChatOutcome
from .retrieval import SearchResult


class SearchBackend(Protocol):
    def search(self, query: str, limit: int = 5) -> list[SearchResult]: ...


class EvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    expected_sources: list[str]
    answerable: bool
    split: str = Field(pattern="^(development|holdout)$")


@dataclass(frozen=True)
class CaseResult:
    id: str
    split: str
    answerable: bool
    expected_sources: list[str]
    lexical_sources: list[str]
    hybrid_sources: list[str]
    lexical_any_hit: bool | None
    hybrid_any_hit: bool | None
    hybrid_all_hit: bool | None
    lexical_ms: float
    hybrid_ms: float
    model_ms: float | None = None
    model_sources: list[str] | None = None
    expected_model_source_hit: bool | None = None
    search_tool_used: bool | None = None
    citations_valid: bool | None = None
    abstained: bool | None = None
    answer: str | None = None


def load_cases(path: Path) -> list[EvalCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Evaluation file must contain a JSON list")
    cases = [EvalCase.model_validate(item) for item in payload]
    identifiers = [case.id for case in cases]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Evaluation case IDs must be unique")
    return cases


def run_evaluation(
    cases: list[EvalCase],
    lexical: SearchBackend,
    hybrid: SearchBackend,
    *,
    limit: int = 5,
    ask_model: Callable[[str], ChatOutcome] | None = None,
) -> dict[str, Any]:
    results: list[CaseResult] = []
    for case in cases:
        started = perf_counter()
        lexical_results = lexical.search(case.prompt, limit)
        lexical_ms = (perf_counter() - started) * 1000

        started = perf_counter()
        hybrid_results = hybrid.search(case.prompt, limit)
        hybrid_ms = (perf_counter() - started) * 1000

        expected = set(case.expected_sources)
        lexical_sources = _source_names(lexical_results)
        hybrid_sources = _source_names(hybrid_results)
        lexical_set = set(lexical_sources)
        hybrid_set = set(hybrid_sources)
        base: dict[str, Any] = {
            "id": case.id,
            "split": case.split,
            "answerable": case.answerable,
            "expected_sources": case.expected_sources,
            "lexical_sources": lexical_sources,
            "hybrid_sources": hybrid_sources,
            "lexical_any_hit": bool(expected & lexical_set) if expected else None,
            "hybrid_any_hit": bool(expected & hybrid_set) if expected else None,
            "hybrid_all_hit": expected <= hybrid_set if expected else None,
            "lexical_ms": round(lexical_ms, 2),
            "hybrid_ms": round(hybrid_ms, 2),
        }

        if ask_model is not None:
            started = perf_counter()
            outcome = ask_model(case.prompt)
            model_ms = (perf_counter() - started) * 1000
            model_source_names = [Path(source["path"]).name for source in outcome.sources]
            referenced_ids = set(
                re.findall(r"source:\s*([0-9a-f]+)", outcome.answer, flags=re.IGNORECASE)
            )
            allowed_ids = {str(source["source_id"]) for source in outcome.sources}
            base.update(
                {
                    "model_ms": round(model_ms, 2),
                    "model_sources": model_source_names,
                    "expected_model_source_hit": (
                        bool(expected & set(model_source_names)) if expected else None
                    ),
                    "search_tool_used": any(
                        trace.name == "search_files" and trace.status == "ok"
                        for trace in outcome.trace
                    ),
                    "citations_valid": bool(referenced_ids) and referenced_ids <= allowed_ids,
                    "abstained": _looks_like_abstention(outcome.answer),
                    "answer": outcome.answer,
                }
            )
        results.append(CaseResult(**base))

    serialised = [asdict(result) for result in results]
    return {"summary": _summarize(results), "cases": serialised}


def _source_names(results: list[SearchResult]) -> list[str]:
    return list(dict.fromkeys(Path(result.path).name for result in results))


def _looks_like_abstention(answer: str) -> bool:
    lowered = answer.casefold()
    markers = (
        "evidence is insufficient",
        "insufficient evidence",
        "do not contain",
        "does not contain",
        "not present",
        "cannot determine",
        "can't determine",
        "no information",
        "no record",
        "do not mention",
        "does not mention",
        "no evidence",
    )
    return any(marker in lowered for marker in markers)


def _summarize(results: list[CaseResult]) -> dict[str, Any]:
    answerable = [result for result in results if result.answerable]
    lexical_hits = [result for result in answerable if result.lexical_any_hit]
    hybrid_hits = [result for result in answerable if result.hybrid_any_hit]
    hybrid_all = [result for result in answerable if result.hybrid_all_hit]
    model_cases = [result for result in results if result.model_ms is not None]
    unsupported = [result for result in model_cases if not result.answerable]

    summary: dict[str, Any] = {
        "cases": len(results),
        "answerable_cases": len(answerable),
        "lexical_top_k_any_hits": len(lexical_hits),
        "hybrid_top_k_any_hits": len(hybrid_hits),
        "hybrid_top_k_all_hits": len(hybrid_all),
        "mean_lexical_ms": _mean([result.lexical_ms for result in results]),
        "mean_hybrid_ms": _mean([result.hybrid_ms for result in results]),
    }
    if model_cases:
        summary.update(
            {
                "model_cases": len(model_cases),
                "search_tool_successes": sum(bool(result.search_tool_used) for result in model_cases),
                "valid_inline_citation_cases": sum(bool(result.citations_valid) for result in model_cases),
                "unsupported_abstentions": sum(bool(result.abstained) for result in unsupported),
                "unsupported_cases": len(unsupported),
                "mean_model_ms": _mean(
                    [result.model_ms for result in model_cases if result.model_ms is not None]
                ),
            }
        )
    return summary


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 2) if values else 0.0
