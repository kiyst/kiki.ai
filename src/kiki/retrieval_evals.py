"""Passage-level retrieval evaluation, independent of answer generation.

Document-level checks hide the failure that matters most for a small answer
model: the right book is retrieved but not the passage that answers the
question. Each case lists evidence groups; a group is satisfied by a retrieved
chunk containing any of its phrases (optionally restricted to documents).
Comparison questions use one group per side.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .retrieval import SearchResult


class SearchBackend(Protocol):
    def search(self, query: str, limit: int = 5) -> list[SearchResult]: ...


class EvidenceGroup(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    phrases: list[str] = Field(min_length=1)
    documents: list[str] = Field(default_factory=list)


class RetrievalCase(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    split: str = Field(pattern="^(development|holdout)$")
    evidence: list[EvidenceGroup] = Field(min_length=1)
    # Records label corrections made after inspecting results, for transparency.
    label_note: str | None = None


def load_retrieval_cases(path: Path) -> list[RetrievalCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Retrieval evaluation file must contain a JSON list")
    cases = [RetrievalCase.model_validate(item) for item in payload]
    identifiers = [case.id for case in cases]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Evaluation case IDs must be unique")
    return cases


def _normalize(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", text).casefold()


def satisfies(result: SearchResult, group: EvidenceGroup) -> bool:
    if group.documents and Path(result.path).name not in group.documents:
        return False
    excerpt = _normalize(result.excerpt)
    return any(_normalize(phrase) in excerpt for phrase in group.phrases)


def score_case(
    case: RetrievalCase, results: list[SearchResult], *, limit: int
) -> dict[str, Any]:
    def is_evidence(result: SearchResult) -> bool:
        return any(satisfies(result, group) for group in case.evidence)

    first_rank = next(
        (rank for rank, result in enumerate(results, start=1) if is_evidence(result)), None
    )
    top = results[:limit]
    covered = sum(any(satisfies(result, group) for result in top) for group in case.evidence)
    return {
        "hit_at_1": bool(results) and is_evidence(results[0]),
        "full_at_k": covered == len(case.evidence),
        "group_recall_at_k": covered / len(case.evidence),
        "first_evidence_rank": first_rank,
        "reciprocal_rank": 1 / first_rank if first_rank else 0.0,
        "top": [f"{Path(result.path).name}:{result.start_location}" for result in top],
    }


def run_retrieval_evaluation(
    cases: list[RetrievalCase],
    backends: dict[str, SearchBackend],
    *,
    limit: int = 5,
) -> dict[str, Any]:
    """Score each backend's actual top-`limit` results, as RAG would receive them."""
    rows: list[dict[str, Any]] = []
    for case in cases:
        for method, backend in backends.items():
            started = perf_counter()
            results = backend.search(case.prompt, limit)
            elapsed = (perf_counter() - started) * 1000
            rows.append(
                {
                    "id": case.id,
                    "split": case.split,
                    "method": method,
                    "ms": round(elapsed, 1),
                    **score_case(case, results, limit=limit),
                }
            )
    return {"summary": _summarize(rows, list(backends)), "cases": rows}


def _summarize(rows: list[dict[str, Any]], methods: list[str]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for method in methods:
        for split in ("development", "holdout", "all"):
            selected = [
                row
                for row in rows
                if row["method"] == method and (split == "all" or row["split"] == split)
            ]
            if not selected:
                continue
            summary[f"{method}/{split}"] = {
                "cases": len(selected),
                "hit_at_1": sum(row["hit_at_1"] for row in selected),
                "full_at_k": sum(row["full_at_k"] for row in selected),
                "mrr": round(mean(row["reciprocal_rank"] for row in selected), 3),
                "mean_ms": round(mean(row["ms"] for row in selected), 1),
            }
    return summary
