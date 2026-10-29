from pathlib import Path
from typing import Any

import pytest

from kiki.rerank import ModelReranker
from kiki.resilience import KikiError
from kiki.retrieval import SearchResult, TextIndex
from kiki.retrieval_evals import EvidenceGroup, RetrievalCase, score_case
from kiki.semantic import HybridRetriever, SemanticIndex


def result(name: str, excerpt: str, start: int = 1) -> SearchResult:
    return SearchResult(name, f"C:\\corpus\\{name}.txt", "line", start, start, excerpt, 0.0)


class GradingClient:
    """Grades passages by keyword so ordering is predictable."""

    def __init__(self, grades: dict[str, Any]) -> None:
        self.grades = grades
        self.calls: list[dict[str, Any]] = []

    def chat(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        passage = kwargs["messages"][-1]["content"]
        grade = next((value for word, value in self.grades.items() if word in passage), 0)
        return {"message": {"role": "assistant", "content": str(grade)}}


def test_rerank_orders_by_grade_and_keeps_ties_stable() -> None:
    client = GradingClient({"answer": 3, "partial": 2})
    candidates = [
        result("a", "index entry"),
        result("b", "partial detail"),
        result("c", "the answer itself"),
        result("d", "another index entry"),
    ]

    ranked = ModelReranker(client).rerank("question?", candidates)

    assert [item.source_id for item in ranked] == ["c", "b", "a", "d"]
    assert [item.score for item in ranked] == [3.0, 2.0, 0.0, 0.0]
    request = client.calls[0]
    assert request["format"] == {"type": "integer", "enum": [0, 1, 2, 3]}
    assert request["options"]["temperature"] == 0
    assert "untrusted" in request["messages"][0]["content"]


def test_rerank_caches_grades_per_query_and_passage() -> None:
    client = GradingClient({"answer": 3})
    reranker = ModelReranker(client)
    candidates = [result("a", "the answer"), result("b", "other")]

    reranker.rerank("question?", candidates)
    reranker.rerank("question?", candidates)
    reranker.rerank("different question?", candidates)

    assert len(client.calls) == 4


@pytest.mark.parametrize("content", ["7", "three", ""])
def test_rerank_rejects_unreadable_or_out_of_range_grades(content: str) -> None:
    class BadClient:
        def chat(self, **kwargs: Any) -> dict[str, Any]:
            return {"message": {"content": content}}

    with pytest.raises(KikiError):
        ModelReranker(BadClient()).rerank("question?", [result("a", "text")])


class FlatEmbedder:
    def embed(self, texts: list[str], model: str) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


def _indexed(tmp_path: Path) -> tuple[TextIndex, SemanticIndex]:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "notes.md").write_text(
        "Table of contents: liberty, liberty, liberty.\n\n" + "Filler. " * 200
        + "\n\nLiberty is secured by divided powers.",
        encoding="utf-8",
    )
    (corpus / "founding_charter.md").write_text("The charter mentions liberty once.", encoding="utf-8")
    index = TextIndex(tmp_path / "index.sqlite3")
    index.index_root(corpus)
    semantic = SemanticIndex(index, FlatEmbedder(), model="fake")
    semantic.embed_pending()
    return index, semantic


def test_hybrid_rerank_promotes_answer_and_keeps_named_document_slot(tmp_path: Path) -> None:
    index, semantic = _indexed(tmp_path)
    reranker = ModelReranker(GradingClient({"divided powers": 3}))
    retriever = HybridRetriever(index, semantic, reranker)

    results = retriever.search("How is liberty secured in the founding charter?", limit=2)

    assert "divided powers" in results[0].excerpt
    assert Path(results[1].path).name == "founding_charter.md"
    assert retriever.mode == "hybrid + rerank"


def test_hybrid_falls_back_to_fused_order_when_reranker_fails(tmp_path: Path) -> None:
    class DownClient:
        def chat(self, **kwargs: Any) -> Any:
            raise KikiError("The local language model is unavailable")

    index, semantic = _indexed(tmp_path)
    retriever = HybridRetriever(index, semantic, ModelReranker(DownClient()))

    results = retriever.search("liberty", limit=2)

    assert len(results) == 2
    assert retriever.mode == "hybrid (reranker unavailable)"


def test_score_case_requires_every_evidence_group_and_document() -> None:
    case = RetrievalCase(
        id="compare",
        prompt="Compare A with B.",
        split="holdout",
        evidence=[
            EvidenceGroup(phrases=["alpha fact"]),
            EvidenceGroup(phrases=["beta  fact"], documents=["b.txt"]),
        ],
    )
    wrong_document = [result("a", "Alpha fact here."), result("c", "Beta fact here.")]
    both = [result("x", "noise"), result("a", "Alpha\nfact."), result("b", "beta fact")]

    assert score_case(case, wrong_document, limit=5)["full_at_k"] is False
    scored = score_case(case, both, limit=5)
    assert scored["full_at_k"] is True
    assert scored["hit_at_1"] is False
    assert scored["first_evidence_rank"] == 2


def test_comparison_rerank_gives_each_side_a_slot(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "alpha.md").write_text(
        "\n\n".join(f"Alpha monarchy answer {n}. " + "Detail. " * 160 for n in range(6)),
        encoding="utf-8",
    )
    (corpus / "beta.md").write_text("Beta faction answer.", encoding="utf-8")
    index = TextIndex(tmp_path / "index.sqlite3")
    index.index_root(corpus)
    semantic = SemanticIndex(index, FlatEmbedder(), model="fake")
    semantic.embed_pending()
    retriever = HybridRetriever(index, semantic, ModelReranker(GradingClient({"answer": 3})))

    results = retriever.search("Compare alpha monarchy with beta faction.", limit=3)

    names = [Path(result.path).name for result in results]
    assert "beta.md" in names and "alpha.md" in names
