from pathlib import Path

from kiki.retrieval import TextIndex
from kiki.semantic import HybridRetriever, SemanticIndex, _query_variants


class FakeEmbedder:
    def embed(self, texts: list[str], model: str) -> list[list[float]]:
        vectors = []
        for text in texts:
            lowered = text.lower()
            vectors.append([1.0, 0.0] if "feline" in lowered or "cat" in lowered else [0.0, 1.0])
        return vectors


class OfflineEmbedder:
    def embed(self, texts: list[str], model: str) -> list[list[float]]:
        raise OSError("embedding service offline")


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


def test_hybrid_search_falls_back_to_lexical_when_embeddings_fail(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "policy.md").write_text("Retry transient failures.", encoding="utf-8")
    index = TextIndex(tmp_path / "index.sqlite3")
    index.index_root(corpus)
    SemanticIndex(index, FakeEmbedder(), model="fake").embed_pending()
    hybrid = HybridRetriever(index, SemanticIndex(index, OfflineEmbedder(), model="fake"))

    results = hybrid.search("transient failures")

    assert results[0].path.endswith("policy.md")
    assert hybrid.last_fallback_reason == "embedding service offline"



def test_named_document_is_represented_even_when_crowded_out(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    # Many commentary paragraphs mention the charter more than the charter itself.
    commentary = "\n\n".join(
        f"Essay {number}: the charter purposes of the charter were debated. " + "Detail. " * 300
        for number in range(30)
    )
    (corpus / "commentary_essays.md").write_text(commentary, encoding="utf-8")
    (corpus / "founding_charter.md").write_text(
        "We establish justice and secure liberty.", encoding="utf-8"
    )
    index = TextIndex(tmp_path / "index.sqlite3")
    index.index_root(corpus)
    semantic = SemanticIndex(index, FakeEmbedder(), model="fake")
    semantic.embed_pending()
    retriever = HybridRetriever(index, semantic)

    results = retriever.search("What purposes does the founding charter state?", limit=3)
    unnamed = retriever.search("What purposes were debated?", limit=3)

    assert [Path(result.path).name for result in results].count("founding_charter.md") == 1
    assert len(results) == 3
    assert all(Path(result.path).name == "commentary_essays.md" for result in unnamed)


def test_qwen3_queries_get_instruction_prefix_but_documents_do_not(tmp_path: Path) -> None:
    from kiki.semantic import query_instruction

    class RecordingEmbedder(FakeEmbedder):
        def __init__(self) -> None:
            self.seen: list[str] = []

        def embed(self, texts: list[str], model: str) -> list[list[float]]:
            self.seen.extend(texts)
            return super().embed(texts, model)

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "pets.md").write_text("A feline companion.", encoding="utf-8")
    index = TextIndex(tmp_path / "index.sqlite3")
    index.index_root(corpus)
    embedder = RecordingEmbedder()
    semantic = SemanticIndex(index, embedder, model="qwen3-embedding:0.6b")

    semantic.embed_pending()
    semantic.search("cat")

    assert embedder.seen[0] == "A feline companion."
    assert embedder.seen[1].startswith("Instruct: ") and embedder.seen[1].endswith("\nQuery:cat")
    assert query_instruction("nomic-embed-text") == ""
