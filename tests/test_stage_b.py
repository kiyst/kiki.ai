"""Stage B prompt layout and the character-sheet lorebook."""
from pathlib import Path

import pytest

from kiki.danger import NOTES, DangerDetector
from kiki.lorebook import load_sheet, sheet_prompt
from kiki.model_client import ChatOutcome, ToolCallingAssistant
from kiki.terminal import VOICE_NOTE, TerminalSession
from kiki.tools import ToolRegistry


def test_the_sheet_loads_with_topics() -> None:
    entries = load_sheet()
    assert len(entries) >= 15
    assert all(entry.topics for entry in entries)
    assert any(entry.taste == "Winter" for entry in entries)


def test_missing_sheet_is_empty(tmp_path) -> None:
    assert load_sheet(tmp_path / "none.md") == []


@pytest.mark.parametrize(("message", "taste"), [
    ("what's your favorite season", "Winter"),
    ("do you like cats", "Cats over dogs"),
    ("tell me a joke", "Jokes on demand"),
    ("you're so smart", "Flattery"),
    ("what music are you into", "Music"),
])
def test_entries_arrive_on_topic(message: str, taste: str) -> None:
    assert f"- {taste}" in sheet_prompt(load_sheet(), [message])


@pytest.mark.parametrize("message", [
    "write a commit message for the login fix",
    "i want to go home",
    "i need help with my code",
    "convert 72 fahrenheit to celsius",
])
def test_nothing_arrives_off_topic(message: str) -> None:
    assert sheet_prompt(load_sheet(), [message]) == ""


def test_at_most_two_entries() -> None:
    text = sheet_prompt(load_sheet(), ["music, cats, winter, sushi and pizza"])
    assert text.count("\n- ") == 2


def _stage_b(tmp_path):
    session = TerminalSession(tmp_path / "index.sqlite3")
    session.prompt_layout = "stage-b"
    session.character_card = "You are Kiki, CARD."
    session.danger = DangerDetector(None)
    return session


def test_stage_b_order_and_size(tmp_path) -> None:
    session = _stage_b(tmp_path)
    system, late = session._stage_b_prompt("what's your favorite season")
    assert system.startswith("You are Kiki, CARD.")
    assert "concise local conversational assistant" not in system
    assert system.index("CARD") < system.index("Default to answering") < system.index("- Winter")
    assert "Commands with several forms" not in system  # the full command list stays out
    assert late == VOICE_NOTE


def test_full_self_knowledge_only_when_asked_about_kiki(tmp_path) -> None:
    session = _stage_b(tmp_path)
    assert "Commands with several forms" in session._stage_b_prompt("what commands do you have")[0]
    assert "Commands with several forms" in session._stage_b_prompt("can you read my files?")[0]


def test_time_sensitive_notes_go_after_the_message(tmp_path) -> None:
    session = _stage_b(tmp_path)
    session.today.add("be nicer today")
    session.danger_kind = "self_harm"
    system, late = session._stage_b_prompt("hey")
    assert "be nicer today" in late and NOTES["self_harm"] in late and VOICE_NOTE in late
    assert "be nicer today" not in system and NOTES["self_harm"] not in system


def test_the_late_note_follows_the_message_but_is_not_saved(tmp_path, monkeypatch) -> None:
    sent = []

    class Client:
        def chat(self, **kwargs):
            sent.append(kwargs["messages"])
            return {"message": {"role": "assistant", "content": "Winter."}}

    monkeypatch.setattr("kiki.terminal.OllamaClient", Client)
    session = _stage_b(tmp_path)
    session.ask("favorite season?")
    last = sent[0][-1]
    assert last["role"] == "user"
    assert last["content"].startswith("favorite season?\n\n[Note from Kiki's code")
    assert last["content"].endswith(VOICE_NOTE)
    assert session.histories["chat"][0] == {"role": "user", "content": "favorite season?"}


def test_v1_layout_is_unchanged(tmp_path, monkeypatch) -> None:
    seen = []

    def fake_ask(self, prompt, history=None):
        seen.append((self.system_prompt, self.late_note))
        return ChatOutcome("ok", [], [])

    monkeypatch.setattr("kiki.terminal.ToolCallingAssistant.ask", fake_ask)
    session = TerminalSession(tmp_path / "index.sqlite3")
    session.ask("hello")
    system, late = seen[0]
    assert system.startswith("You are a concise local conversational assistant.")
    assert late == ""


def test_assistant_without_a_note_sends_the_message_alone() -> None:
    sent = []

    class Client:
        def chat(self, **kwargs):
            sent.append(kwargs["messages"][-1]["content"])
            return {"message": {"role": "assistant", "content": "ok"}}

    ToolCallingAssistant(Client(), ToolRegistry(include_search=False)).ask("hi")
    assert sent == ["hi"]
