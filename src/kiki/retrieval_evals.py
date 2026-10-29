"""Passage-level retrieval evaluation, independent of answer generation.

Document-level checks hide the failure that matters most for a small answer
model: the right book is retrieved but not the passage that answers the
question. Each case lists evidence groups; a group is satisfied by a retrieved
chunk containing any of its phrases (optionally restricted to documents).
Comparison questions use one group per side.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import subprocess
import threading
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Any, Protocol

import httpx

from pydantic import BaseModel, ConfigDict, Field

from .extraction import EXTRACTION_VERSION
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
        "any_at_k": covered > 0,
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
                    "rerank_ms": round(float(getattr(backend, "last_rerank_ms", 0.0)), 1),
                    "retrieval_mode": getattr(backend, "mode", "lexical"),
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
                "any_at_k": sum(row["any_at_k"] for row in selected),
                "full_at_k": sum(row["full_at_k"] for row in selected),
                "mrr": round(mean(row["reciprocal_rank"] for row in selected), 3),
                "mean_ms": round(mean(row["ms"] for row in selected), 1),
                "mean_rerank_ms": round(mean(row["rerank_ms"] for row in selected), 1),
                "fallbacks": sum(
                    "unavailable" in row["retrieval_mode"] or "fallback" in row["retrieval_mode"]
                    for row in selected
                ),
            }
    return summary


def evaluation_environment(
    database: Path, cases: Path, *, models: list[str]
) -> dict[str, Any]:
    """Everything needed to tell whether two receipts are comparable."""
    return {
        "git": _git_state(),
        "database": _database_identity(database),
        "cases_sha256": hashlib.sha256(cases.read_bytes()).hexdigest()[:16],
        "ollama": _ollama_models([model for model in models if model]),
        "gpu": _gpu_name(),
    }


def _git_state() -> dict[str, Any]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10, check=True
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, timeout=10, check=True
        ).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "dirty_files": None}
    return {"commit": commit, "dirty_files": status}


def _database_identity(database: Path) -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{database.resolve().as_posix()}?mode=ro", uri=True)
    try:
        files = connection.execute("SELECT path, content_hash FROM files ORDER BY path").fetchall()
        chunks = connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        embeddings = connection.execute(
            "SELECT model, COUNT(*) FROM chunk_embeddings GROUP BY model"
        ).fetchall()
    finally:
        connection.close()
    # Filenames and content hashes only, so the identity is stable across checkouts.
    identity = "\n".join(f"{Path(path).name}\0{digest}" for path, digest in files)
    return {
        "corpus_identity": hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16],
        "files": len(files),
        "chunks": chunks,
        "embeddings": dict(embeddings),
        "extraction_version": EXTRACTION_VERSION,
    }


def _ollama_models(models: list[str]) -> dict[str, Any]:
    try:
        version = httpx.get("http://127.0.0.1:11434/api/version", timeout=3).json()["version"]
        installed = httpx.get("http://127.0.0.1:11434/api/tags", timeout=3).json()["models"]
    except (httpx.HTTPError, KeyError, ValueError):
        return {"version": None, "digests": {}}
    digests = {item["name"]: str(item.get("digest", ""))[:12] for item in installed}
    return {
        "version": version,
        "digests": {model: digests.get(model, "missing") for model in dict.fromkeys(models)},
    }


def _gpu_name() -> str | None:
    sample = _nvidia_smi("name,memory.total")
    return sample[0] if sample else None


def _nvidia_smi(fields: str) -> list[str] | None:
    try:
        output = subprocess.run(
            ["nvidia-smi", f"--query-gpu={fields}", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return [line.strip() for line in output.splitlines() if line.strip()] or None


class GpuMemorySampler:
    """Polls whole-GPU memory use during an evaluation and keeps the peak.

    Whole-device numbers include other processes (the desktop, browsers), so the
    report also keeps the idle reading taken before the run started.
    """

    def __init__(self, interval: float = 1.0) -> None:
        self.interval = interval
        self.idle_mib: int | None = None
        self.peak_mib: int | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _read(self) -> int | None:
        sample = _nvidia_smi("memory.used")
        try:
            return int(float(sample[0])) if sample else None
        except ValueError:
            return None

    def __enter__(self) -> GpuMemorySampler:
        self.idle_mib = self._read()
        self.peak_mib = self.idle_mib
        if self.idle_mib is not None:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        return self

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            value = self._read()
            if value is not None and (self.peak_mib is None or value > self.peak_mib):
                self.peak_mib = value

    def __exit__(self, *exc_info: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)

    def report(self) -> dict[str, Any]:
        return {
            "measured": self.idle_mib is not None,
            "idle_mib": self.idle_mib,
            "peak_mib": self.peak_mib,
            "method": "nvidia-smi memory.used, whole device, 1 s polling",
        }
