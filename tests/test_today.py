"""Temporary tone requests: what counts as one, when it ends, and where it reaches."""
import json
from datetime import datetime

import pytest
from rich.console import Console

from kiki.model_client import ChatOutcome
from kiki.terminal import TerminalSession, _handle_command
from kiki.today import (
    MAX_CHARACTERS,
    MAX_REQUESTS,
    TodayFile,
    is_tone_request,
    is_tone_reset,
    request_expiry,
    request_topic,
)

EVENING = datetime(2026, 10, 30, 21, 15)


def _file(tmp_path, clock):
    return TodayFile(tmp_path / "kiki-today.json", now=lambda: clock[0])


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
    "no jokes for an hour",
    "be serious for the next 30 minutes",
    "keep it short until 5pm",
    "be nicer this week",
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
    "I worked until 5pm",
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


@pytest.mark.parametrize(("text", "ends"), [
    ("be nicer today", datetime(2026, 10, 31, 4, 0)),
    ("be nicer tonight", datetime(2026, 10, 31, 4, 0)),
    ("be nicer this week", datetime(2026, 10, 31, 4, 0)),  # the file only reaches 4 AM
    ("no jokes for an hour", datetime(2026, 10, 30, 22, 15)),
    ("no jokes for half an hour", datetime(2026, 10, 30, 21, 45)),
    ("no jokes for 2 hours", datetime(2026, 10, 30, 23, 15)),
    ("be serious for the next 30 minutes", datetime(2026, 10, 30, 21, 45)),
    ("no jokes for 500 hours", datetime(2026, 10, 31, 21, 15)),  # capped at a day
    ("keep it short until 11pm", datetime(2026, 10, 30, 23, 0)),
    ("keep it short until 10", datetime(2026, 10, 30, 22, 0)),  # the next 10 o'clock
    ("keep it short until 9", datetime(2026, 10, 31, 9, 0)),  # 9 PM has passed
    ("keep it short until 8:30am", datetime(2026, 10, 31, 8, 30)),
])
def test_when_requests_end(text: str, ends: datetime) -> None:
    assert request_expiry(text, EVENING) == ends


def test_a_request_just_after_midnight_still_ends_at_4am() -> None:
    assert request_expiry("be nicer today", datetime(2026, 10, 31, 0, 30)) == datetime(2026, 10, 31, 4, 0)
    assert request_expiry("be nicer today", datetime(2026, 10, 31, 4, 30)) == datetime(2026, 11, 1, 4, 0)


def test_requests_expire_on_their_own(tmp_path) -> None:
    clock = [EVENING]
    today = _file(tmp_path, clock)
    today.add("no jokes for an hour")
    today.add("be nicer today")
    assert today.requests() == ["no jokes for an hour", "be nicer today"]
    assert "(until 10:15 PM)" in today.prompt() and "(until tomorrow 4:00 AM)" in today.prompt()
    clock[0] = datetime(2026, 10, 30, 23, 0)
    assert today.requests() == ["be nicer today"]
    clock[0] = datetime(2026, 10, 31, 4, 0)
    assert today.requests() == []
    assert today.prompt() == ""


@pytest.mark.parametrize(("text", "topic"), [
    ("be nicer today", "warmth"), ("be meaner today", "warmth"), ("go easy on me today", "warmth"),
    ("go easy on the jokes today", "humor"), ("no sarcasm for now", "humor"),
    ("keep answers short today", "length"), ("be more serious today", "seriousness"),
    ("no swearing today", "language"),
])
def test_topics(text: str, topic: str) -> None:
    assert request_topic(text) == topic


def test_a_newer_request_on_the_same_topic_replaces_the_older(tmp_path) -> None:
    today = _file(tmp_path, [EVENING])
    today.add("be nicer today")
    today.add("no jokes today")
    today.add("be meaner today")
    assert today.requests() == ["no jokes today", "be meaner today"]


def test_requests_are_bounded_cleaned_and_private_data_refused(tmp_path) -> None:
    today = _file(tmp_path, [EVENING])
    for number in range(MAX_REQUESTS + 3):
        today.add(f"remember the {number} thing today")  # no topic, so none replace
    assert len(today.requests()) == MAX_REQUESTS
    assert today.requests()[-1] == "remember the 10 thing today"
    # Terminal control codes are shown as text, never stored live.
    assert today.add("be\x1b[31m nicer   today").text == "be\\x1b[31m nicer today"
    with pytest.raises(ValueError):
        today.add("x" * (MAX_CHARACTERS + 1))
    with pytest.raises(ValueError):
        today.add("be nicer today, my password is hunter2")
    assert today.clear() is True
    assert today.clear() is False


@pytest.mark.parametrize("content", [
    "not json", "[]", '{"requests": "be nice"}',
    '{"requests": [{"text": "be nice"}]}',
    '{"requests": [{"text": "be nice", "until": "never"}]}',
    '{"requests": [{"text": "be nice", "until": "2030-01-01T00:00"}]}',  # hand-edited far future
    '{"date": "2026-10-30", "requests": ["be nice"]}',  # the first version's format
])
def test_damaged_or_edited_file_is_ignored(tmp_path, content: str) -> None:
    path = tmp_path / "kiki-today.json"
    path.write_text(content)
    assert TodayFile(path, now=lambda: EVENING).requests() == []


def test_written_file_is_readable(tmp_path) -> None:
    today = _file(tmp_path, [EVENING])
    today.add("no jokes for an hour")
    data = json.loads((tmp_path / "kiki-today.json").read_text())
    assert data == {"requests": [{"text": "no jokes for an hour", "topic": "humor", "until": "2026-10-30T22:15"}]}


def test_chat_saves_the_request_and_tells_the_model(tmp_path, monkeypatch) -> None:
    session = TerminalSession(tmp_path / "index.sqlite3")
    seen = {}

    def fake_ask(self, prompt, history=None):
        seen["system"] = self.system_prompt
        return ChatOutcome("Fine. Gentler. Briefly.", [], [])

    monkeypatch.setattr("kiki.terminal.ToolCallingAssistant.ask", fake_ask)
    session.ask("be nicer to me today")
    assert session.today.requests() == ["be nicer to me today"]
    assert "Temporary requests from the user" in seen["system"]
    assert "Kiki's code just saved" in seen["system"]
    assert "(until " in seen["system"]

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
    assert outcome.answer.startswith("Saved until ")
    assert outcome.answer.endswith("no jokes while we work. /today clear lifts it sooner.")
    assert session.histories["rag"] == []


def test_today_command(tmp_path) -> None:
    console = Console(record=True, width=160)
    session = TerminalSession(tmp_path / "index.sqlite3")
    _handle_command(console, session, "/today")
    _handle_command(console, session, "/today keep answers short for an hour")
    _handle_command(console, session, "/today")
    _handle_command(console, session, "/today clear")
    shown = console.export_text()
    assert "No temporary requests right now." in shown
    assert "Saved: keep answers short for an hour (until " in shown
    assert "- keep answers short for an hour (until " in shown
    assert "Cleared today's requests." in shown
    assert session.today.requests() == []
