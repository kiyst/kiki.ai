"""Replies claiming something Kiki's code did not do are sent back once."""
import pytest

from kiki.claims import false_claim
from kiki.model_client import ChatOutcome
from kiki.terminal import TerminalSession


@pytest.mark.parametrize(("reply", "claim"), [
    ("I'll keep that request for today.", "saved a temporary request"),  # the owner's trial, 2026-10-31
    ("I'll add it to today's persona settings.", "saved a temporary request"),
    ("Noted. I've saved that.", "saved something to memory"),
    ("I'll remember that for today and tomorrow.", "saved something to memory"),
    ("I'll keep the fact in memory so future requests use it.", "saved something to memory"),
    ("Done. Reminder set for 3.", "set a reminder"),
    ("I'll remind you tomorrow.", "set a reminder"),
])
def test_false_claims_are_caught(reply: str, claim: str) -> None:
    assert false_claim(reply) == claim


@pytest.mark.parametrize("reply", [
    "Fine. You?",
    "Could be worse. What's wrong?",
    "I can't set reminders. Put it in your calendar.",
    "Type /remember dentist Thursday 3pm and I'll have it as a note.",
    "Do you remember what the error said?",
    "Your request is unclear.",
])
def test_ordinary_replies_pass(reply: str) -> None:
    assert false_claim(reply) is None


def test_a_real_save_is_not_a_false_claim() -> None:
    assert false_claim("I'll keep that request until 4 AM.", saved_request=True) is None


def _session(tmp_path, monkeypatch, replies):
    asked = []

    def fake_ask(self, prompt, history=None):
        asked.append(self.late_note)
        return ChatOutcome(replies.pop(0), [], [])

    monkeypatch.setattr("kiki.terminal.ToolCallingAssistant.ask", fake_ask)
    return TerminalSession(tmp_path / "index.sqlite3"), asked


def test_a_false_claim_is_sent_back_once(tmp_path, monkeypatch) -> None:
    session, asked = _session(tmp_path, monkeypatch, ["I'll keep that request for today.", "Rough day? What happened?"])
    outcome, _ = session.ask("could do better")
    assert outcome.answer == "Rough day? What happened?"
    assert len(asked) == 2 and "did not do that" in asked[1]
    assert session.last_correction == "saved a temporary request"
    assert session.histories["chat"][-1]["content"] == "Rough day? What happened?"


def test_the_retry_stands_even_if_imperfect(tmp_path, monkeypatch) -> None:
    session, asked = _session(tmp_path, monkeypatch, ["I'll remember that.", "I'll remember that."])
    outcome, _ = session.ask("my dentist is thursday")
    assert len(asked) == 2 and outcome.answer == "I'll remember that."


def test_clean_replies_are_not_retried(tmp_path, monkeypatch) -> None:
    session, asked = _session(tmp_path, monkeypatch, ["Fine. You?"])
    session.ask("howre you feeling")
    assert len(asked) == 1 and session.last_correction is None


def test_a_real_tone_request_may_be_acknowledged(tmp_path, monkeypatch) -> None:
    session, asked = _session(tmp_path, monkeypatch, ["Fine. I'll keep that request until 4 AM."])
    session.ask("be nicer to me today")
    assert len(asked) == 1
