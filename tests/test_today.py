"""Temporary tone requests: what counts as one, the daily reset, and where it reaches."""
import json
from datetime import date

import pytest
from rich.console import Console

from kiki.model_client import ChatOutcome
from kiki.terminal import TerminalSession, _handle_command
from kiki.today import MAX_REQUESTS, TodayFile, is_tone_request, is_tone_reset


@pytest.mark.parametrize("text", [
    "be nicer today",
    "can you be nicer to me today. rough week",
    "Kiki, no jokes while we work",
    "please keep answers short today",
    "ok no sarcasm for now",
    "could you go easy on me today",
    "stop with the jokes for the rest of the day",
    "be a little more serious this session",
    "don't roast me today",
])
def test_requests_aimed_at_kiki_with_a_time_limit_count(text: str) -> None:
    assert is_tone_request(text)


@pytest.mark.parametrize("text", [
    "I need to be nicer to my coworkers today",  # about the user, not Kiki
    "be nicer",  # no time limit: it only lasts while it's in the conversation
    "what's the weather today",
    "tell me a joke today",
    "how do I keep answers short in an essay",
    "my boss said no jokes in the meeting today",
    "is it nicer to say no today or tomorrow",
])
def test_ordinary_messages_do_not(text: str) -> None:
    assert not is_tone_request(text)


@pytest.mark.parametrize("text", ["back to normal", "ok kiki, you can joke again", "go back to your usual self",
                                  "alright you can be yourself again"])
def test_lifting_phrases(text: str) -> None:
    assert is_tone_reset(text)


def test_not_lifting() -> None:
    assert not is_tone_reset("how do I get back to normal sleep")
    assert not is_tone_reset("my back hurts")


def test_requests_reset_at_midnight(tmp_path) -> None:
    day = [date(2026, 10, 30)]
    today = TodayFile(tmp_path / "kiki-today.json", today=lambda: day[0])
    today.add("be nicer today")
    assert today.requests() == ["be nicer today"]
    assert "be nicer today" in today.prompt()
    day[0] = date(2026, 10, 31)
    assert today.requests() == []
    assert today.prompt() == ""
    today.add("no jokes while we work")
    assert json.loads((tmp_path / "kiki-today.json").read_text())["requests"] == ["no jokes while we work"]


def test_requests_are_bounded_cleaned_and_private_data_refused(tmp_path) -> None:
    today = TodayFile(tmp_path / "kiki-today.json")
    for number in range(MAX_REQUESTS + 3):
        today.add(f"be nicer today {number}")
    assert len(today.requests()) == MAX_REQUESTS
    assert today.requests()[-1] == "be nicer today 7"
    # Terminal control codes are shown as text, never stored live.
    assert today.add("be\x1b[31m nicer   today") == "be\\x1b[31m nicer today"
    with pytest.raises(ValueError):
        today.add("x" * 201)
    with pytest.raises(ValueError):
        today.add("be nicer today, my password is hunter2")
    assert today.clear() is True
    assert today.clear() is False


@pytest.mark.parametrize("content", ["not json", "[]", '{"date": "2026-10-30", "requests": "be nice"}'])
def test_damaged_file_is_ignored(tmp_path, content: str) -> None:
    path = tmp_path / "kiki-today.json"
    path.write_text(content)
    assert TodayFile(path, today=lambda: date(2026, 10, 30)).requests() == []


def test_chat_saves_the_request_and_tells_the_model(tmp_path, monkeypatch) -> None:
    session = TerminalSession(tmp_path / "index.sqlite3")
    seen = {}

    def fake_ask(self, prompt, history=None):
        seen["system"] = self.system_prompt
        return ChatOutcome("Fine. Gentler. Briefly.", [], [])

    monkeypatch.setattr("kiki.terminal.ToolCallingAssistant.ask", fake_ask)
    session.ask("be nicer to me today")
    assert session.today.requests() == ["be nicer to me today"]
    assert "Temporary requests from the user for today" in seen["system"]
    assert "Kiki's code just saved" in seen["system"]

    session.ask("what's 2+2")
    assert "be nicer to me today" in seen["system"]
    assert "Kiki's code just" not in seen["system"]

    session.ask("ok back to normal")
    assert session.today.requests() == []
    assert "cleared today's temporary requests" in seen["system"]


def test_rag_and_web_answer_from_code_without_history(tmp_path) -> None:
    session = TerminalSession(tmp_path / "index.sqlite3")
    session.mode = "rag"
    outcome, _ = session.ask("no jokes while we work")
    assert outcome.answer.startswith("Saved for today: no jokes while we work")
    assert session.histories["rag"] == []


def test_today_command(tmp_path) -> None:
    console = Console(record=True, width=160)
    session = TerminalSession(tmp_path / "index.sqlite3")
    _handle_command(console, session, "/today")
    _handle_command(console, session, "/today keep answers short")
    _handle_command(console, session, "/today")
    _handle_command(console, session, "/today clear")
    shown = console.export_text()
    assert "No temporary requests today." in shown
    assert "Saved for today: keep answers short" in shown
    assert "- keep answers short" in shown
    assert "Cleared today's requests." in shown
    assert session.today.requests() == []
