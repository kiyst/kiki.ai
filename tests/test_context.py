"""The reading-space setting: sizes, what the model is sent, and the /context command."""
from typing import Any

import pytest
from rich.console import Console

from kiki.context import CONTEXT_SIZES, context_name, context_tokens, history_limits
from kiki.model_client import ToolCallingAssistant
from kiki.terminal import TerminalSession, _handle_command
from kiki.tools import ToolRegistry


class FakeClient:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def chat(self, **kwargs: Any) -> dict[str, Any]:
        self.requests.append(kwargs)
        return {"message": {"role": "assistant", "content": "ok"}}


def _history(turns: int) -> list[dict[str, str]]:
    history = []
    for number in range(turns):
        history.append({"role": "user", "content": f"question {number}"})
        history.append({"role": "assistant", "content": f"answer {number}"})
    return history


def test_sizes_names_and_default(monkeypatch) -> None:
    monkeypatch.delenv("KIKI_CONTEXT", raising=False)
    assert context_tokens() == 8_192
    assert context_tokens("SMALL") == 4_096
    assert context_tokens(" max ") == 32_768
    monkeypatch.setenv("KIKI_CONTEXT", "large")
    assert context_tokens() == 16_384
    assert context_name(16_384) == "large"
    assert context_name(12_000) == "12000 tokens"
    for bad in ["huge", "8192", "-1", "4k"]:
        with pytest.raises(ValueError):
            context_tokens(bad)


def test_history_scales_with_the_reading_space() -> None:
    # 4K keeps the original 12 messages and 4,000 characters.
    assert history_limits(4_096) == (12, 4_000)
    assert history_limits(8_192) == (24, 8_000)
    assert history_limits(32_768) == (96, 32_000)
    assert history_limits(1) == (12, 4_000)


@pytest.mark.parametrize("size", list(CONTEXT_SIZES.values()))
def test_model_is_sent_the_chosen_size_and_matching_history(size: int) -> None:
    client = FakeClient()
    assistant = ToolCallingAssistant(client, ToolRegistry(include_search=False), context_tokens=size)
    assistant.ask("now", history=_history(60))
    request = client.requests[0]
    assert request["options"]["num_ctx"] == size
    sent = [m for m in request["messages"] if m["role"] in {"user", "assistant"}][:-1]
    assert len(sent) == history_limits(size)[0]
    assert sent[-1]["content"] == "answer 59"


def test_default_assistant_stays_at_the_4k_baseline() -> None:
    client = FakeClient()
    ToolCallingAssistant(client, ToolRegistry(include_search=False)).ask("hi")
    assert client.requests[0]["options"]["num_ctx"] == 4_096


def test_context_command_shows_sets_and_refuses(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("KIKI_CONTEXT", raising=False)
    console = Console(record=True, width=160)
    session = TerminalSession(tmp_path / "index.sqlite3")
    assert session.context_tokens == 8_192

    _handle_command(console, session, "/context")
    shown = console.export_text()
    assert "standard (8192 tokens)" in shown and "KIKI_CONTEXT" in shown

    _handle_command(console, session, "/context large")
    assert session.context_tokens == 16_384
    _handle_command(console, session, "/context enormous")
    assert session.context_tokens == 16_384
    assert "Choose one of" in console.export_text()


def test_only_chat_gets_the_larger_reading_space(tmp_path, monkeypatch) -> None:
    # At 8K, web and document answers were slower and no better
    # (evals/receipts/context/), so they stay at the 4K baseline.
    from kiki.model_client import ChatOutcome

    seen = []

    def fake_ask(self, prompt, history=None):
        seen.append(self.context_tokens)
        return ChatOutcome("ok", [], [])

    monkeypatch.setattr("kiki.terminal.ToolCallingAssistant.ask", fake_ask)
    session = TerminalSession(tmp_path / "index.sqlite3")
    session.context_tokens = 16_384
    session.ask("hello")
    session.mode = "rag"
    session.ask("what does the contract say about payment")
    assert seen == [16_384, 4_096]


def test_bad_environment_value_falls_back_instead_of_crashing(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("KIKI_CONTEXT", "all of it")
    assert TerminalSession(tmp_path / "index.sqlite3").context_tokens == 8_192
