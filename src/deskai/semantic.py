from __future__ import annotations

import math
import re
from array import array
from dataclasses import replace
from time import sleep
from typing import Any, Protocol

from .resilience import DeskAIError, ErrorCode

from .retrieval import SearchResult, TextIndex


class EmbeddingClient(Protocol):
    def embed(self, texts: list[str], model: str) -> list[list[float]]: ...


class OllamaEmbeddingClient:
    def __init__(
        self,
        host: str | None = None,
        timeout: float = 120,
        max_attempts: int = 2,
    ) -> None:
        from ollama import Client

        self.client = Client(host=host, timeout=timeout)
        self.max_attempts = max(1, max_attempts)

    def embed(self, texts: list[str], model: str) -> list[list[float]]:
        last_error: Exception | None = None
        for attempt in range(self.max_attempts):
            try:
                response = self.client.embed(model=model, input=texts)
                vectors = getattr(response, "embeddings", None)
                if not isinstance(vectors, (list, tuple)):
                    raise DeskAIError(
                        "Ollama returned a malformed embedding response",
                        code=ErrorCode.MODEL_RESPONSE,
                    )
                return [list(vector) for vector in vectors]
            except DeskAIError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt + 1 < self.max_attempts:
                    sleep(0.2 * (2**attempt))
        raise DeskAIError(
            "The embedding model is unavailable",
            code=ErrorCode.SERVICE_UNAVAILABLE,
            retryable=True,
        ) from last_error


class SemanticIndex:
    def __init__(
        self,
        index: TextIndex,
        client: EmbeddingClient,
        model: str = "qwen3-embedding:0.6b",
        minimum_score: float = 0.2,
    ) -> None:
        self.index = index
        self.client = client
        self.model = model
        self.minimum_score = minimum_score

    def embed_pending(self, batch_size: int = 16) -> dict[str, int]:
        if not 1 <= batch_size <= 64:
            raise ValueError("Batch size must be between 1 and 64")
        embedded = batches = 0
        while chunks := self.index.chunks_needing_embeddings(self.model, batch_size):
            vectors = self.client.embed([chunk.text for chunk in chunks], self.model)
            if len(vectors) != len(chunks):
                raise RuntimeError("Embedding service returned the wrong number of vectors")
            encoded: list[tuple[int, int, bytes]] = []
            for chunk, vector in zip(chunks, vectors, strict=True):
                if not vector or not all(math.isfinite(value) for value in vector):
                    raise RuntimeError("Embedding service returned an invalid vector")
                packed = array("f", vector)
                encoded.append((chunk.chunk_id, len(packed), packed.tobytes()))
            self.index.save_embeddings(self.model, encoded)
            embedded += len(encoded)
            batches += 1
        return {"embedded": embedded, "batches": batches, "total": self.index.embedding_count(self.model)}

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        if not query.strip():
            raise ValueError("Query must not be empty")
        if not 1 <= limit <= 20:
            raise ValueError("Limit must be between 1 and 20")
        rows = self.index.embedding_rows(self.model)
        if not rows:
            return []
        query_vector = self.client.embed([query], self.model)[0]
        scored: list[SearchResult] = []
        for row in rows:
            vector = array("f")
            vector.frombytes(row["vector"])
            if len(vector) != row["dimensions"] or len(vector) != len(query_vector):
                continue
            score = _cosine(query_vector, vector)
            if not math.isfinite(score):
                continue
            if score < self.minimum_score:
                continue
            scored.append(
                SearchResult(
                    source_id=row["source_id"],
                    path=row["path"],
                    location_kind=row["location_kind"],
                    start_location=int(row["start_location"]),
                    end_location=int(row["end_location"]),
                    excerpt=row["content"],
                    score=score,
                )
            )
        return sorted(scored, key=lambda result: result.score, reverse=True)[:limit]


class HybridRetriever:
    """Reciprocal-rank fusion over lexical and local semantic candidates."""

    def __init__(self, lexical: TextIndex, semantic: SemanticIndex) -> None:
        self.lexical = lexical
        self.semantic = semantic
        self.last_fallback_reason: str | None = None

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        self.last_fallback_reason = None
        candidate_limit = min(20, max(limit * 3, 10))
        by_key: dict[tuple[str, str, int, int], SearchResult] = {}
        scores: dict[tuple[str, str, int, int], float] = {}
        result_lists: list[list[SearchResult]] = []
        for variant in _query_variants(query):
            result_lists.append(self.lexical.search(variant, candidate_limit))
            if self.last_fallback_reason is None:
                try:
                    result_lists.append(self.semantic.search(variant, candidate_limit))
                except Exception as exc:
                    # RAG remains available through SQLite FTS when Ollama embeddings fail.
                    self.last_fallback_reason = str(exc)
        for results in result_lists:
            for rank, result in enumerate(results, start=1):
                key = (
                    result.source_id,
                    result.location_kind,
                    result.start_location,
                    result.end_location,
                )
                by_key[key] = result
                scores[key] = scores.get(key, 0.0) + 1.0 / (60 + rank)
        ranked = sorted(scores, key=scores.get, reverse=True)[:limit]
        return [replace(by_key[key], score=scores[key]) for key in ranked]


def _query_variants(query: str) -> list[str]:
    """Split explicit comparisons so both requested subjects receive evidence."""
    variants = [query.strip()]
    comparison = re.sub(r"^\s*compare\s+", "", query, flags=re.IGNORECASE)
    if comparison != query:
        sides = re.split(r"\s+\b(?:with|versus|vs\.?)\b\s+", comparison, maxsplit=1, flags=re.IGNORECASE)
        variants.extend(side.strip(" .?!") for side in sides if len(side.split()) >= 2)
    return list(dict.fromkeys(variant for variant in variants if variant))


def _cosine(left: list[float], right: array[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return float("nan")
    return dot / (left_norm * right_norm)

