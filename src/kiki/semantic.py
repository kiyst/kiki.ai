from __future__ import annotations

import math
import re
from array import array
from collections.abc import Collection
from dataclasses import replace
from time import perf_counter, sleep
from typing import Any, Protocol

from .resilience import KikiError, ErrorCode

from .rerank import Reranker
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
                    raise KikiError(
                        "Ollama returned a malformed embedding response",
                        code=ErrorCode.MODEL_RESPONSE,
                    )
                return [list(vector) for vector in vectors]
            except KikiError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt + 1 < self.max_attempts:
                    sleep(0.2 * (2**attempt))
        raise KikiError(
            "The embedding model is unavailable",
            code=ErrorCode.SERVICE_UNAVAILABLE,
            retryable=True,
        ) from last_error


# Qwen3-Embedding is trained with instruction-prefixed queries and bare
# documents; omitting the prefix measurably lowers retrieval quality.
_QUERY_INSTRUCTIONS = {
    "qwen3-embedding": (
        "Instruct: Given a question, retrieve passages from the indexed documents "
        "that answer it\nQuery:"
    ),
}


def query_instruction(model: str) -> str:
    family = model.split(":", 1)[0].casefold()
    return _QUERY_INSTRUCTIONS.get(family, "")


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
        self._query_vectors: dict[tuple[str, str], list[float]] = {}

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

    def search(
        self, query: str, limit: int = 5, source_ids: Collection[str] | None = None
    ) -> list[SearchResult]:
        if not query.strip():
            raise ValueError("Query must not be empty")
        if not 1 <= limit <= 100:
            raise ValueError("Limit must be between 1 and 100")
        rows = self.index.embedding_rows(self.model)
        if source_ids is not None:
            rows = [row for row in rows if row["source_id"] in source_ids]
        if not rows:
            return []
        query_vector = self._query_vector(query)
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
                    title=row["title"],
                )
            )
        return sorted(scored, key=lambda result: result.score, reverse=True)[:limit]

    def _query_vector(self, query: str) -> list[float]:
        # Named-document coverage re-searches the same query; embed it once.
        key = (self.model, query)
        if key not in self._query_vectors:
            if len(self._query_vectors) >= 32:
                self._query_vectors.clear()
            self._query_vectors[key] = self.client.embed(
                [query_instruction(self.model) + query], self.model
            )[0]
        return self._query_vectors[key]


class HybridRetriever:
    """Reciprocal-rank fusion over lexical and semantic candidates, optionally
    followed by reranking and one bounded recovery search.

    The retriever owns retrieval retries (bounded, deterministic, deduplicated),
    so evidence never depends on the answer model choosing to search again.
    """

    def __init__(
        self,
        lexical: TextIndex,
        semantic: SemanticIndex,
        reranker: Reranker | None = None,
        *,
        candidates: int = 20,
        recovery: bool = False,
    ) -> None:
        if not 1 <= candidates <= 100:
            raise ValueError("Candidates must be between 1 and 100")
        self.lexical = lexical
        self.semantic = semantic
        self.reranker = reranker
        self.candidates = candidates
        self.recovery = recovery
        self.last_recovery: dict[str, Any] | None = None
        self.last_fallback_reason: str | None = None
        self.last_rerank_error: str | None = None
        self.last_rerank_ms = 0.0

    @property
    def mode(self) -> str:
        if self.last_fallback_reason:
            return "lexical fallback (embedding service unavailable)"
        if self.reranker is None:
            return "hybrid"
        if self.last_rerank_error:
            return "hybrid (reranker unavailable)"
        return f"hybrid + rerank ({self.reranker.name})"

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        self.last_fallback_reason = None
        self.last_rerank_error = None
        self.last_rerank_ms = 0.0
        self.last_recovery = None
        variants = _query_variants(query)
        if self.reranker is None:
            ranked = self._fuse(variants, min(20, max(limit * 3, 10)))
        else:
            budget = max(limit, self.candidates)
            pool = self._fuse(variants, max(20, budget))[:budget]
            started = perf_counter()
            try:
                if len(variants) > 1:
                    ranked = self._rerank_comparison(variants[1:], pool, budget)
                else:
                    ranked = self.reranker.rerank(query, pool)
                    if self.recovery:
                        # Comparisons already search each side separately.
                        ranked = self._recover(query, ranked, budget)
            except Exception as exc:
                # Answers stay available with fused ordering if reranking fails.
                self.last_rerank_error = str(exc)
                ranked = pool
            self.last_rerank_ms = (perf_counter() - started) * 1000
        top = ranked[:limit]
        # A document named in the question ("the Declaration") gets at least one
        # slot; otherwise long works that discuss it can crowd out the source itself.
        present = {result.source_id for result in top}
        missing = [
            source_id
            for source_id in self.lexical.named_sources(query)
            if source_id not in present
        ][:limit]
        if not missing:
            return top
        additions: list[SearchResult] = []
        for source_id in missing:
            # Prefer the best-ranked candidate already scored for this document.
            best = [result for result in ranked if result.source_id == source_id]
            if not best:
                best = self._fuse(variants, 20, (source_id,))
            if best:
                additions.append(best[0])
        return top[: limit - len(additions)] + additions

    def _rerank_comparison(
        self, sides: list[str], pool: list[SearchResult], budget: int
    ) -> list[SearchResult]:
        """Rerank each side of "Compare X with Y" separately and share the slots.

        Scoring every passage against the whole comparison lets whichever side
        has more matching text take every slot. Each side instead gets its own
        candidates (within the same scoring budget) scored against that side.
        """
        assert self.reranker is not None
        per_side = max(1, budget // len(sides))
        rankings = [
            self.reranker.rerank(side, self._fuse([side], max(20, per_side))[:per_side])
            for side in sides
        ]
        merged: list[SearchResult] = []
        seen: set[tuple[str, int, int]] = set()

        def take(result: SearchResult) -> None:
            key = (result.source_id, result.start_location, result.end_location)
            if key not in seen:
                seen.add(key)
                merged.append(result)

        # Each side's best passage is guaranteed a slot; the rest compete by score
        # (all from the same reranker), with earlier side positions winning ties.
        for ranking in rankings:
            if ranking:
                take(ranking[0])
        remainder = [
            (position, result)
            for ranking in rankings
            for position, result in enumerate(ranking[1:], start=1)
        ]
        for _, result in sorted(remainder, key=lambda item: (-item[1].score, item[0])):
            take(result)
        for result in pool:
            take(result)
        return merged

    def _recover(
        self, query: str, ranked: list[SearchResult], budget: int
    ) -> list[SearchResult]:
        """One bounded retry when the best reranked passage looks weak.

        Rewrites are deterministic (no model call): a search restricted to the
        documents the question names, a keyword form that keeps names and quoted
        phrases, and up to two parts of a broad "X and Y" question. Only new
        candidates are scored, against the original question, so the merged list
        stays on one reranker scale.
        """
        assert self.reranker is not None
        best = ranked[0].score if ranked else 0.0
        if ranked and best >= self.reranker.strong_score:
            return ranked
        rewrites = recovery_queries(query)
        named = self.lexical.named_sources(query)
        searches: list[tuple[str, tuple[str, ...] | None]] = [(text, None) for text in rewrites]
        if named:
            searches.insert(0, (rewrites[0] if rewrites else query, tuple(named)))
        seen = {(r.source_id, r.start_location, r.end_location) for r in ranked}
        per_search = [self._fuse([text], 20, sources) for text, sources in searches]
        # Scoring budget for the retry: half the first pass, at least four passages.
        # Take candidates round-robin so every rewrite's best results get a turn.
        allowance = max(4, budget // 2)
        fresh: list[SearchResult] = []
        for rank in range(20):
            for results in per_search:
                if rank < len(results) and len(fresh) < allowance:
                    key = (results[rank].source_id, results[rank].start_location, results[rank].end_location)
                    if key not in seen:
                        seen.add(key)
                        fresh.append(results[rank])
        self.last_recovery = {
            "best_score": best,
            "queries": [text for text, _ in searches],
            "new_candidates": len(fresh),
            "improved": False,
        }
        if not fresh:
            return ranked
        rescored = self.reranker.rerank(query, fresh)
        self.last_recovery["improved"] = rescored[0].score > best
        merged = sorted(enumerate([*ranked, *rescored]), key=lambda item: (-item[1].score, item[0]))
        return [result for _, result in merged]

    def _fuse(
        self,
        variants: list[str],
        candidate_limit: int,
        source_ids: Collection[str] | None = None,
    ) -> list[SearchResult]:
        by_key: dict[tuple[str, str, int, int], SearchResult] = {}
        scores: dict[tuple[str, str, int, int], float] = {}
        result_lists: list[list[SearchResult]] = []
        for variant in variants:
            try:
                result_lists.append(self.lexical.search(variant, candidate_limit, source_ids))
            except ValueError:
                # A rewrite with no searchable terms contributes nothing.
                pass
            if self.last_fallback_reason is None:
                try:
                    result_lists.append(
                        self.semantic.search(variant, candidate_limit, source_ids)
                    )
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
        ranked = sorted(scores, key=scores.get, reverse=True)
        return [replace(by_key[key], score=scores[key], ranker="fused") for key in ranked]


def _query_variants(query: str) -> list[str]:
    """Split explicit comparisons so both requested subjects receive evidence."""
    variants = [query.strip()]
    comparison = re.sub(r"^\s*compare\s+", "", query, flags=re.IGNORECASE)
    if comparison != query:
        sides = re.split(r"\s+\b(?:with|versus|vs\.?)\b\s+", comparison, maxsplit=1, flags=re.IGNORECASE)
        variants.extend(side.strip(" .?!") for side in sides if len(side.split()) >= 2)
    return list(dict.fromkeys(variant for variant in variants if variant))


_QUESTION_WORDS = {
    "a", "about", "according", "an", "and", "are", "as", "at", "be", "by", "can",
    "could", "describe", "did", "do", "does", "explain", "for", "from", "give", "has",
    "have", "how", "in", "is", "it", "its", "me", "of", "on", "or", "say", "says",
    "should", "tell", "that", "the", "their", "there", "these", "they", "this", "to",
    "was", "were", "what", "when", "where", "which", "who", "whom", "why", "with",
    "would", "you", "your", "them", "him", "her", "his", "we", "us", "our", "i", "my",
}


def recovery_queries(query: str, limit: int = 3) -> list[str]:
    """Deterministic rewrites for one recovery search, the original excluded.

    1. Keyword form: question words dropped; quoted phrases and names kept intact.
    2. Parts: a broad "X and Y" (or "X; Y") question split into at most two parts
       that each keep at least two content words.
    """
    quoted = re.findall(r"[\"“]([^\"”]{2,80})[\"”]", query)
    remainder = re.sub(r"[\"“][^\"”]{2,80}[\"”]", " ", query)
    words = re.findall(r"[A-Za-z][A-Za-z'’-]*|\d+", remainder)
    kept = [word for word in words if word.casefold() not in _QUESTION_WORDS]
    keyword = " ".join([*(f'"{phrase}"' for phrase in quoted), *kept]).strip()
    rewrites: list[str] = []
    if keyword and keyword.casefold() != query.strip(" ?.!").casefold():
        rewrites.append(keyword)
    parts = re.split(r"\s*;\s*|\s+\band\b\s+", remainder.strip(" ?.!"), flags=re.IGNORECASE)
    if len(parts) > 1:
        for part in parts[:2]:
            content = [
                word
                for word in re.findall(r"[A-Za-z][A-Za-z'’-]*", part)
                if word.casefold() not in _QUESTION_WORDS
            ]
            if len(content) >= 2:
                rewrites.append(" ".join(content))
    return list(dict.fromkeys(rewrites))[:limit]


def _cosine(left: list[float], right: array[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return float("nan")
    return dot / (left_norm * right_norm)

