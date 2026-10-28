from pathlib import Path
from typing import Any

import pytest

from deskai.model_client import ToolCallingAssistant, ToolLoopLimitError, _bounded_search_result
from deskai.retrieval import TextIndex
from deskai.tools import ToolRegistry


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
            {"source_id": "abc", "citation": "[source:abc] file", "excerpt": "x" * 5_000},
            {"source_id": "def", "citation": "[source:def] file", "excerpt": "y" * 5_000},
        ],
    }

    bounded, used = _bounded_search_result(result, 1_000)

    assert used <= 1_050
    assert [item["source_id"] for item in bounded["data"]] == ["abc", "def"]
    assert all("truncated" in item["excerpt"] for item in bounded["data"])


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
    fake = FakeClient(
        [{"message": {"role": "assistant", "content": "Validation failures are final."}}]
    )

    outcome = ToolCallingAssistant(
        fake, ToolRegistry(index), pre_retrieve=True
    ).ask("What should not be retried?")

    assert outcome.trace[0].round == 0
    assert outcome.trace[0].name == "search_files"
    assert outcome.sources[0]["path"].endswith("evidence.md")
    assert fake.requests[0]["messages"][-1]["role"] == "tool"

