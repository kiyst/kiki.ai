"""Bounded, deterministic retrieval recovery owned by the retriever."""

from pathlib import Path

import pytest

from kiki.retrieval import SearchResult, TextIndex
from kiki.semantic import HybridRetriever, SemanticIndex, recovery_queries
from kiki.settings import RetrievalSettings, SettingsError


class FlatEmbedder:
    def __init__(self, hidden: str | None = None) -> None:
        self.hidden = hidden

    def embed(self, texts: list[str], model: str) -> list[list[float]]:
        return [[0.0, 1.0] if self.hidden and self.hidden in t else [1.0, 0.0] for t in texts]


class KeywordReranker:
    """Scores 0.9 for passages containing a keyword, else 0.1; logs every call."""

    name = "keyword"
    model = "fake"
    strong_score = 0.5

    def __init__(self, keyword: str) -> None:
        self.keyword = keyword
        self.calls: list[tuple[str, int]] = []

    def rerank(self, query: str, results: list[SearchResult]) -> list[SearchResult]:
        from dataclasses import replace

        self.calls.append((query, len(results)))
        scored = [
            replace(r, score=0.9 if self.keyword in r.excerpt else 0.1, ranker="keyword")
            for r in results
        ]
        return sorted(scored, key=lambda r: -r.score)


def _corpus(
    tmp_path: Path, files: dict[str, str], hidden: str | None = None
) -> tuple[TextIndex, SemanticIndex]:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for name, text in files.items():
        (corpus / name).write_text(text, encoding="utf-8")
    index = TextIndex(tmp_path / "index.sqlite3")
    index.index_root(corpus)
    semantic = SemanticIndex(index, FlatEmbedder(hidden), model="fake")
    semantic.embed_pending()
    return index, semantic


def test_recovery_queries_keep_names_and_quotes_and_split_broad_questions() -> None:
    assert recovery_queries('Why did "no taxation without representation" matter to Paine?') == [
        '"no taxation without representation" matter Paine'
    ]
    assert recovery_queries("What does Beard say about railways and trusts and strikes?") == [
        "Beard railways trusts strikes",
        "Beard railways",
    ]
    assert recovery_queries("liberty") == []


def test_recovery_is_skipped_when_first_pass_evidence_is_strong(tmp_path: Path) -> None:
    index, semantic = _corpus(tmp_path, {"a.md": "Liberty answer here.", "b.md": "Liberty aside."})
    reranker = KeywordReranker("answer")
    retriever = HybridRetriever(index, semantic, reranker, recovery=True)

    retriever.search("What about liberty?", limit=2)

    assert len(reranker.calls) == 1
    assert retriever.last_recovery is None


def test_weak_first_pass_triggers_one_bounded_retry_with_new_candidates_only(tmp_path: Path) -> None:
    # Common terms crowd the first pool; only the "militia drills" part finds the
    # rare-term target, and the embedder never surfaces it semantically.
    files = {f"filler{n}.md": f"Liberty records and liberty records {n}." for n in range(8)}
    files["target.md"] = "Militia drills answer."
    index, semantic = _corpus(tmp_path, files, hidden="Drills")
    reranker = KeywordReranker("answer")
    retriever = HybridRetriever(index, semantic, reranker, candidates=4, recovery=True)

    results = retriever.search("What do the records say about liberty and militia drills?", limit=3)

    assert "answer" in results[0].excerpt
    assert retriever.last_recovery is not None
    assert retriever.last_recovery["improved"] is True
    first_pool, retry_pool = reranker.calls[0][1], reranker.calls[1][1]
    assert len(reranker.calls) == 2
    assert retry_pool <= max(4, 4 // 2)
    assert first_pool == 4
    assert all(result.ranker == "keyword" for result in results)


def test_recovery_disabled_by_default(tmp_path: Path) -> None:
    index, semantic = _corpus(tmp_path, {"a.md": "Liberty filler.", "b.md": "Muster answer."})
    reranker = KeywordReranker("answer")
    retriever = HybridRetriever(index, semantic, reranker, candidates=1)

    retriever.search("liberty and muster rolls", limit=1)

    assert len(reranker.calls) == 1


def test_comparisons_do_not_trigger_recovery(tmp_path: Path) -> None:
    index, semantic = _corpus(tmp_path, {"a.md": "Alpha monarchy text.", "b.md": "Beta faction text."})
    reranker = KeywordReranker("answer")
    retriever = HybridRetriever(index, semantic, reranker, recovery=True)

    retriever.search("Compare alpha monarchy with beta faction.", limit=2)

    assert retriever.last_recovery is None


def test_recovery_failure_falls_back_to_fused_order(tmp_path: Path) -> None:
    class FailsOnRetry(KeywordReranker):
        def rerank(self, query, results):
            if self.calls:
                raise RuntimeError("reranker crashed")
            return super().rerank(query, results)

    index, semantic = _corpus(tmp_path, {"a.md": "Liberty filler.", "b.md": "Muster drills text."})
    retriever = HybridRetriever(index, semantic, FailsOnRetry("answer"), candidates=1, recovery=True)

    results = retriever.search("liberty and muster drills", limit=1)

    assert results and retriever.mode == "hybrid (reranker unavailable)"


def test_recovery_setting_parses_on_and_off() -> None:
    assert RetrievalSettings.from_environment({"KIKI_RAG_RECOVERY": "on"}).recovery is True
    assert RetrievalSettings.from_environment({"KIKI_RAG_RECOVERY": "0"}).recovery is False
    with pytest.raises(SettingsError, match="KIKI_RAG_RECOVERY must be on or off"):
        RetrievalSettings.from_environment({"KIKI_RAG_RECOVERY": "sometimes"})
