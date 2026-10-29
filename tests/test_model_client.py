import json
from pathlib import Path
from typing import Any

import pytest

from kiki.model_client import (
    ToolCallingAssistant,
    ToolLoopLimitError,
    _bounded_search_result,
    _message_dict,
    _tool_call,
    resolve_citations,
)
from kiki.retrieval import SearchResult, TextIndex, passage_identifier
from kiki.resilience import KikiError
from kiki.tools import ToolRegistry


class FakeClient:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = responses
        self.requests: list[dict[str, Any]] = []

    def chat(self, **kwargs: Any) -> dict[str, Any]:
        self.requests.append(kwargs)
        return self.responses.pop(0)


def test_search_evidence_is_bounded_without_dropping_citations() -> None:
    result = {
        "status": "ok",
        "error": None,
        "data": [
            {"source_id": "abc", "passage_id": "pabc", "citation": "[source:pabc] file", "excerpt": "x" * 5_000},
            {"source_id": "def", "passage_id": "pdef", "citation": "[source:pdef] file", "excerpt": "y" * 5_000},
        ],
    }

    bounded, used = _bounded_search_result(result, 1_000)

    assert used <= 1_050
    assert [item["passage_id"] for item in bounded["data"]] == ["pabc", "pdef"]
    assert all("truncated" in item["excerpt"] for item in bounded["data"])



def test_long_excerpt_is_focused_on_query_terms_not_its_opening() -> None:
    filler = "Unrelated front matter about printing and editions. " * 40
    excerpt = filler + "\nThe Congress shall have Power To borrow Money on the credit of the United States.\n" + filler
    result = {
        "status": "ok",
        "error": None,
        "data": [
            {
                "source_id": "abc",
                "passage_id": "pabc",
                "path": "C:\\corpus\\constitution.txt",
                "location_kind": "line",
                "start_location": 190,
                "end_location": 246,
                "score": 3.2,
                "citation": "[source:abc] C:\\corpus\\constitution.txt (lines 190-246)",
                "excerpt": excerpt,
            }
        ],
    }

    bounded, used = _bounded_search_result(result, 600, "What borrowing powers does Congress have?")

    item = bounded["data"][0]
    assert "borrow Money" in item["excerpt"]
    assert item["excerpt"].startswith("[…] ")
    assert used <= 650
    assert item == {
        "cite": "[source:pabc]",
        "passage_id": "pabc",
        "document": "constitution.txt",
        "location": "lines 190-246",
        "excerpt": item["excerpt"],
    }

def test_model_selected_tool_result_is_propagated(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "policy.md").write_text("Retry transient failures three times.", encoding="utf-8")
    index = TextIndex(tmp_path / "index.sqlite3")
    index.index_root(corpus)
    fake = FakeClient(
        [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "search_files", "arguments": {"query": "retry"}}}
                    ],
                }
            },
            {"message": {"role": "assistant", "content": "The policy allows three attempts."}},
        ]
    )

    outcome = ToolCallingAssistant(fake, ToolRegistry(index)).ask("What is the retry policy?")

    assert outcome.answer == "The policy allows three attempts."
    assert outcome.trace[0].name == "search_files"
    tool_message = fake.requests[1]["messages"][-1]
    assert tool_message["role"] == "tool"
    assert "policy.md" in tool_message["content"]


def test_unknown_model_tool_is_returned_as_error(tmp_path: Path) -> None:
    fake = FakeClient(
        [
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {"function": {"name": "run_shell", "arguments": {"command": "whoami"}}}
                    ],
                }
            },
            {"message": {"role": "assistant", "content": "That tool is unavailable."}},
        ]
    )
    registry = ToolRegistry(TextIndex(tmp_path / "index.sqlite3"))

    outcome = ToolCallingAssistant(fake, registry).ask("Run a command")

    assert outcome.trace[0].status == "error"
    assert "Unknown tool" in fake.requests[1]["messages"][-1]["content"]


def test_tool_loop_is_bounded(tmp_path: Path) -> None:
    tool_response = {
        "message": {
            "role": "assistant",
            "tool_calls": [{"function": {"name": "search_files", "arguments": {"query": "x"}}}],
        }
    }
    fake = FakeClient([tool_response, tool_response])
    registry = ToolRegistry(TextIndex(tmp_path / "index.sqlite3"))

    with pytest.raises(ToolLoopLimitError, match="round limit"):
        ToolCallingAssistant(fake, registry, max_rounds=2).ask("Keep searching")


def test_reasoning_text_is_not_user_visible(tmp_path: Path) -> None:
    fake = FakeClient(
        [{"message": {"role": "assistant", "content": "private reasoning</think>\nFinal answer."}}]
    )
    registry = ToolRegistry(TextIndex(tmp_path / "index.sqlite3"))

    outcome = ToolCallingAssistant(fake, registry).ask("Answer briefly")

    assert outcome.answer == "Final answer."


def test_pre_retrieval_does_not_depend_on_model_tool_choice(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "evidence.md").write_text(
        "The source says validation failures must not be retried.", encoding="utf-8"
    )
    index = TextIndex(tmp_path / "index.sqlite3")
    index.index_root(corpus)
    source_id = index.search("validation", 1)[0].passage_id
    fake = FakeClient(
        [
            {
                "message": {
                    "role": "assistant",
                    "content": f"Validation failures are final. [source:{source_id}]",
                }
            }
        ]
    )

    outcome = ToolCallingAssistant(
        fake, ToolRegistry(index), pre_retrieve=True
    ).ask("What should not be retried?")

    assert outcome.trace[0].round == 0
    assert outcome.trace[0].name == "search_files"
    assert outcome.sources[0]["path"].endswith("evidence.md")
    assert fake.requests[0]["messages"][-1]["role"] == "tool"


def test_string_encoded_tool_arguments_are_parsed() -> None:
    name, arguments = _tool_call(
        {"function": {"name": "search_files", "arguments": '{"query": "history"}'}}
    )

    assert name == "search_files"
    assert arguments == {"query": "history"}


def test_malformed_tool_call_is_classified() -> None:
    with pytest.raises(KikiError) as caught:
        _tool_call({"wrong": "shape"})

    assert caught.value.code == "tool_call_format"


def test_malformed_model_response_is_classified() -> None:
    with pytest.raises(KikiError) as caught:
        _message_dict({"not_message": {}})

    assert caught.value.code == "model_response"

    with pytest.raises(KikiError):
        _message_dict({"message": {"role": "assistant", "content": 42}})


def test_rag_answer_without_valid_citation_is_rejected(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "evidence.md").write_text("The event occurred in 1776.", encoding="utf-8")
    index = TextIndex(tmp_path / "index.sqlite3")
    index.index_root(corpus)
    fake = FakeClient(
        [
            {"message": {"role": "assistant", "content": "It happened in 1776."}},
            {"message": {"role": "assistant", "content": "It happened in 1776 [source:made-up]."}},
        ]
    )

    outcome = ToolCallingAssistant(
        fake, ToolRegistry(index), pre_retrieve=True
    ).ask("When did the event happen?")

    assert outcome.answer.startswith("Evidence is insufficient to verify")
    assert len(fake.requests) == 2
    assert fake.requests[1]["messages"][-1]["content"].startswith("Citation check")


def test_rag_repairs_missing_citations_once(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "evidence.md").write_text("The event occurred in 1776.", encoding="utf-8")
    index = TextIndex(tmp_path / "index.sqlite3")
    index.index_root(corpus)
    source_id = index.search("event", 1)[0].passage_id
    fake = FakeClient(
        [
            {"message": {"role": "assistant", "content": "It happened in 1776."}},
            {"message": {"role": "assistant", "content": f"It happened in 1776. [source:{source_id}]"}},
        ]
    )

    outcome = ToolCallingAssistant(
        fake, ToolRegistry(index), pre_retrieve=True
    ).ask("When did the event happen?")

    assert outcome.answer == f"It happened in 1776. [source:{source_id}]"


@pytest.mark.parametrize(
    "citation",
    ["[source:{id}]", "[source: {id}]", "[source:{id}, lines 1-1]", "[source:{id} lines 1]"],
)
def test_grounding_accepts_common_citation_variants(tmp_path: Path, citation: str) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "evidence.md").write_text("The event occurred in 1776.", encoding="utf-8")
    index = TextIndex(tmp_path / "index.sqlite3")
    index.index_root(corpus)
    source_id = index.search("event", 1)[0].passage_id
    answer = "It happened in 1776. " + citation.format(id=source_id)
    fake = FakeClient([{"message": {"role": "assistant", "content": answer}}])

    outcome = ToolCallingAssistant(
        fake, ToolRegistry(index), pre_retrieve=True
    ).ask("When did the event happen?")

    assert outcome.answer == answer
    assert len(fake.requests) == 1


def test_rag_reconsiders_model_abstention_when_retrieval_found_evidence(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "paine.md").write_text(
        "Thomas Paine opposed hereditary monarchy and supported independence.",
        encoding="utf-8",
    )
    index = TextIndex(tmp_path / "index.sqlite3")
    index.index_root(corpus)
    source_id = index.search("Thomas Paine", 1)[0].passage_id
    fake = FakeClient(
        [
            {"message": {"role": "assistant", "content": "Evidence is insufficient."}},
            {
                "message": {
                    "role": "assistant",
                    "content": f"Paine opposed hereditary monarchy. [source:{source_id}]",
                }
            },
        ]
    )

    outcome = ToolCallingAssistant(
        fake, ToolRegistry(index), pre_retrieve=True
    ).ask("What were Thomas Paine's views?")

    assert outcome.answer.startswith("Paine opposed")
    assert len(fake.requests) == 2
    assert "Reconsider once" in fake.requests[1]["messages"][-1]["content"]



def _indexed_evidence(tmp_path: Path) -> TextIndex:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "evidence.md").write_text("The event occurred in 1776.", encoding="utf-8")
    index = TextIndex(tmp_path / "index.sqlite3")
    index.index_root(corpus)
    return index


def test_document_ids_are_not_accepted_as_passage_citations(tmp_path: Path) -> None:
    index = _indexed_evidence(tmp_path)
    hit = index.search("event", 1)[0]
    document_cited = f"It happened in 1776. [source:{hit.source_id}]"
    fake = FakeClient(
        [
            {"message": {"role": "assistant", "content": document_cited}},
            {"message": {"role": "assistant", "content": document_cited}},
        ]
    )

    outcome = ToolCallingAssistant(fake, ToolRegistry(index), pre_retrieve=True).ask("When?")

    assert outcome.answer.startswith("Evidence is insufficient to verify")


def test_sources_resolve_to_passage_span_and_exact_shown_evidence(tmp_path: Path) -> None:
    index = _indexed_evidence(tmp_path)
    hit = index.search("event", 1)[0]
    answer = f"It happened in 1776. [source:{hit.passage_id}] Also [source:pmissing0000]."
    fake = FakeClient([{"message": {"role": "assistant", "content": f"It happened in 1776. [source:{hit.passage_id}]"}}])

    outcome = ToolCallingAssistant(fake, ToolRegistry(index), pre_retrieve=True).ask("When did the event happen?")

    (source,) = outcome.sources
    assert source["passage_id"] == hit.passage_id
    assert (source["location_kind"], source["start_location"], source["end_location"]) == ("line", 1, 1)
    assert source["document"] == "evidence.md"
    assert source["evidence"] == "The event occurred in 1776."
    resolved = resolve_citations(answer, outcome.sources)
    assert [item["resolved"] for item in resolved] == [True, False]
    assert resolved[0]["evidence"] == "The event occurred in 1776."
    model_payload = json.loads(fake.requests[0]["messages"][-1]["content"])
    assert model_payload["data"][0]["cite"] == f"[source:{hit.passage_id}]"
    assert "source_id" not in model_payload["data"][0]
    assert "path" not in model_payload["data"][0]


def test_passages_dropped_by_the_evidence_budget_are_not_citable(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for number in range(3):
        (corpus / f"note{number}.md").write_text(f"Liberty note {number}. " + "x" * 400, encoding="utf-8")
    index = TextIndex(tmp_path / "index.sqlite3")
    index.index_root(corpus)
    fake = FakeClient([{"message": {"role": "assistant", "content": "Evidence is insufficient."}}] * 2)

    outcome = ToolCallingAssistant(
        fake, ToolRegistry(index), pre_retrieve=True, max_evidence_characters=1_000, passages=5
    ).ask("liberty?")

    shown = json.loads(fake.requests[0]["messages"][-1]["content"])["data"]
    assert {source["passage_id"] for source in outcome.sources} == {item["passage_id"] for item in shown}


def test_passage_ids_are_stable_and_distinct_per_span() -> None:
    first = SearchResult("doc1", "a.txt", "line", 1, 9, "x", 0.0)
    same = SearchResult("doc1", "a.txt", "line", 1, 9, "different excerpt window", 3.0)
    other = SearchResult("doc1", "a.txt", "line", 10, 19, "x", 0.0)

    assert first.passage_id == same.passage_id == passage_identifier("doc1", "line", 1, 9)
    assert first.passage_id != other.passage_id
    assert first.citation == f"[source:{first.passage_id}] a.txt (lines 1-9)"
    assert SearchResult("d", "b.pdf", "page", 3, 4, "x", 0.0).location_label == "pages 3-4"
