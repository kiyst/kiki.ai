from pathlib import Path

from deskai.retrieval import TextIndex
from deskai.semantic import HybridRetriever, SemanticIndex, _query_variants


class FakeEmbedder:
    def embed(self, texts: list[str], model: str) -> list[list[float]]:
        vectors = []
        for text in texts:
            lowered = text.lower()
            vectors.append([1.0, 0.0] if "feline" in lowered or "cat" in lowered else [0.0, 1.0])
        return vectors


def test_semantic_search_finds_concept_without_keyword_overlap(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "pets.md").write_text("A feline companion likes warm windows.", encoding="utf-8")
    (corpus / "database.md").write_text("The database uses transactions.", encoding="utf-8")
    index = TextIndex(tmp_path / "index.sqlite3")
    index.index_root(corpus)
    semantic = SemanticIndex(index, FakeEmbedder(), model="fake")

    receipt = semantic.embed_pending(batch_size=1)
    results = semantic.search("cat", limit=1)

    assert receipt == {"embedded": 2, "batches": 2, "total": 2}
    assert results[0].path.endswith("pets.md")
    assert index.search("cat") == []


def test_hybrid_search_fuses_both_rankings(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "pets.md").write_text("A feline companion likes warm windows.", encoding="utf-8")
    index = TextIndex(tmp_path / "index.sqlite3")
    index.index_root(corpus)
    semantic = SemanticIndex(index, FakeEmbedder(), model="fake")
    semantic.embed_pending()

    results = HybridRetriever(index, semantic).search("feline cat", limit=1)

    assert results[0].path.endswith("pets.md")
    assert results[0].score > 0


def test_explicit_comparison_is_searched_as_full_query_and_both_sides() -> None:
    assert _query_variants("Compare Paine's monarchy with Madison's faction remedy.") == [
        "Compare Paine's monarchy with Madison's faction remedy.",
        "Paine's monarchy",
        "Madison's faction remedy",
    ]

