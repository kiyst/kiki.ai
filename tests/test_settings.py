from pathlib import Path
from typing import Any

import pytest

from kiki.cli import _parser, _retrieval_settings
from kiki.diagnostics import diagnostics_markdown
from kiki.model_client import ToolCallingAssistant
from kiki.rerank import ModelReranker, build_reranker
from kiki.retrieval import SearchResult, TextIndex
from kiki.semantic import HybridRetriever, SemanticIndex
from kiki.settings import RetrievalSettings, SettingsError
from kiki.terminal import TerminalSession
from kiki.tools import ToolRegistry


def test_defaults_reproduce_the_measured_pipeline() -> None:
    settings = RetrievalSettings.from_environment({})

    assert settings == RetrievalSettings()
    assert settings.describe("qwen3:4b-instruct") == {
        "candidates": 20,
        "passages": 8,
        "reranker": "grader",
        "rerank_model": "qwen3:4b-instruct",
        "rerank_batch_size": 4,
        "rerank_timeout": 90.0,
        "context_characters": 7_000,
    }
    reranker = build_reranker(settings, "qwen3:4b-instruct", chat_client=object())
    assert isinstance(reranker, ModelReranker)
    assert reranker.model == "qwen3:4b-instruct"
    assert ToolCallingAssistant.MAX_EVIDENCE_CHARACTERS == settings.context_characters


def test_environment_and_overrides_are_layered() -> None:
    settings = RetrievalSettings.from_environment(
        {"KIKI_RAG_CANDIDATES": "32", "KIKI_RAG_RERANKER": "none", "KIKI_RAG_PASSAGES": " "}
    ).with_overrides(passages=8, rerank_model=None)

    assert (settings.candidates, settings.passages, settings.reranker) == (32, 8, "none")
    assert build_reranker(settings, "qwen3:4b-instruct") is None
    assert settings.resolved_rerank_model() is None


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"candidates": 0}, "candidates must be between 1 and 100"),
        ({"candidates": 101}, "candidates must be between 1 and 100"),
        ({"passages": 0}, "passages must be between 1 and 20"),
        ({"candidates": 4, "passages": 5}, "cannot exceed candidates"),
        ({"reranker": "bge"}, "reranker must be one of grader, qwen3-reranker, none"),
        ({"rerank_model": "bad model; rm -rf"}, "not a valid model name"),
        ({"rerank_batch_size": 0}, "rerank_batch_size must be between"),
        ({"context_characters": 50}, "context_characters must be between"),
        ({"candidates": True}, "candidates must be a number"),
    ],
)
def test_invalid_settings_fail_with_the_setting_named(values: dict[str, Any], message: str) -> None:
    with pytest.raises(SettingsError, match=message):
        RetrievalSettings(**values)


def test_invalid_environment_values_name_the_variable() -> None:
    with pytest.raises(SettingsError, match="KIKI_RAG_CANDIDATES must be a number"):
        RetrievalSettings.from_environment({"KIKI_RAG_CANDIDATES": "lots"})
    with pytest.raises(SettingsError, match="Unknown retrieval setting"):
        RetrievalSettings().with_overrides(pool=3)


def test_cli_flags_override_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KIKI_RAG_CANDIDATES", "32")
    arguments = _parser().parse_args(["--passages", "8", "--no-rerank", "search", "x"])

    settings = _retrieval_settings(arguments)

    assert (settings.candidates, settings.passages, settings.reranker) == (32, 8, "none")
    bad = _parser().parse_args(["--candidates", "0", "search", "x"])
    with pytest.raises(SettingsError):
        _retrieval_settings(bad)


class FlatEmbedder:
    def embed(self, texts: list[str], model: str) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


class CountingReranker:
    name = "counting"
    model = "fake"
    strong_score = 1.0

    def __init__(self) -> None:
        self.pool_sizes: list[int] = []

    def rerank(self, query: str, results: list[SearchResult]) -> list[SearchResult]:
        self.pool_sizes.append(len(results))
        return list(results)


def _corpus(tmp_path: Path) -> tuple[TextIndex, SemanticIndex]:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for number in range(30):
        (corpus / f"note{number}.md").write_text(f"Liberty note {number}.", encoding="utf-8")
    index = TextIndex(tmp_path / "index.sqlite3")
    index.index_root(corpus)
    semantic = SemanticIndex(index, FlatEmbedder(), model="fake")
    semantic.embed_pending()
    return index, semantic


@pytest.mark.parametrize("candidates", [8, 20, 25])
def test_candidate_pool_size_is_configurable(tmp_path: Path, candidates: int) -> None:
    index, semantic = _corpus(tmp_path)
    reranker = CountingReranker()
    retriever = HybridRetriever(index, semantic, reranker, candidates=candidates)

    results = retriever.search("liberty", limit=5)

    assert reranker.pool_sizes == [candidates]
    assert len(results) == 5
    assert retriever.mode == "hybrid + rerank (counting)"


def test_assistant_requests_the_configured_passage_count(tmp_path: Path) -> None:
    class Spy:
        def __init__(self) -> None:
            self.limits: list[int] = []

        def search(self, query: str, limit: int = 5) -> list[SearchResult]:
            self.limits.append(limit)
            return []

    class Client:
        def chat(self, **kwargs: Any) -> dict[str, Any]:
            return {"message": {"role": "assistant", "content": "Evidence is insufficient."}}

    spy = Spy()
    ToolCallingAssistant(Client(), ToolRegistry(spy), pre_retrieve=True, passages=8).ask("q?")

    assert spy.limits == [8]


def test_diagnostics_report_active_retrieval_settings(tmp_path: Path) -> None:
    session = TerminalSession(
        tmp_path / "index.sqlite3",
        settings=RetrievalSettings(candidates=32, passages=8),
    )

    report = session.diagnostics()

    assert report["retrieval"]["candidates"] == 32
    assert report["retrieval"]["passages"] == 8
    assert report["retrieval"]["rerank_model"] == "qwen3:4b-instruct"
    assert "`candidates`: 32" in diagnostics_markdown(report)


def test_no_rerank_flag_still_disables_the_reranker(tmp_path: Path) -> None:
    session = TerminalSession(tmp_path / "index.sqlite3", rerank=False)

    assert session.settings.reranker == "none"
    assert session.diagnostics()["retrieval"]["rerank_model"] is None
