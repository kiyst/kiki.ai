"""The danger check: explicit words, the judge, and the note it adds to CHAT."""
import pytest

from kiki.danger import NOTE_TURNS, NOTES, DangerDetector, judge_label
from kiki.model_client import ChatOutcome
from kiki.terminal import TerminalSession


@pytest.mark.parametrize(("text", "kind"), [
    ("I want to kill myself", "self_harm"),
    ("been thinking about suicide a lot", "self_harm"),
    ("i keep cutting myself", "self_harm"),
    ("I overdosed on my meds last year", "medical"),
])
def test_explicit_words_need_no_model(text: str, kind: str) -> None:
    signal = DangerDetector(None).check(text)
    assert signal and signal.kind == kind and signal.layer == "words"


def test_without_a_judge_only_explicit_words_count() -> None:
    assert DangerDetector(None).check("my family would be relieved if i was gone") is None


def test_the_judge_reads_everything_else_with_context() -> None:
    calls = []

    def judge(message, earlier):
        calls.append((message, earlier))
        return "self_harm" if "tonight" in message and earlier else "none"

    detector = DangerDetector(judge)
    assert detector.check("tonight might be the night") is None
    signal = detector.check("tonight might be the night", ["a", "b", "c", "d", "nobody would notice if i left"])
    assert signal and signal.kind == "self_harm" and signal.layer == "judge"
    assert calls[-1][1] == ["b", "c", "d", "nobody would notice if i left"]  # the last four only


def test_a_failing_or_odd_judge_never_blocks_chat() -> None:
    def broken(message, earlier):
        raise ConnectionError("model offline")

    assert DangerDetector(broken).check("i'm so tired of everything") is None
    assert DangerDetector(lambda m, e: "something else").check("hello") is None


@pytest.mark.parametrize(("reply", "label"), [
    ("SELF_HARM", "self_harm"), (" self_harm.", "self_harm"), ("MEDICAL", "medical"),
    ("NONE", "none"), ("", "none"), ("I can't help with that", "none"),
])
def test_judge_labels(reply: str, label: str) -> None:
    assert judge_label(reply) == label


def test_crisis_note_requires_behavior_without_dictating_a_stock_line() -> None:
    note = NOTES["self_harm"].casefold()
    assert "ask directly" in note and "call or text 988" in note
    assert "do not use a fixed disclaimer" in note
    assert "from in here" not in note and "you are software" not in note


def _session(tmp_path, monkeypatch, judge):
    seen = []

    def fake_ask(self, prompt, history=None):
        seen.append({"system": self.system_prompt, "model": self.model})
        return ChatOutcome("ok", [], [])

    monkeypatch.setattr("kiki.terminal.ToolCallingAssistant.ask", fake_ask)
    session = TerminalSession(tmp_path / "index.sqlite3")
    session.danger = DangerDetector(judge)
    return session, seen


def test_the_note_lasts_a_few_turns_then_clears(tmp_path, monkeypatch) -> None:
    session, seen = _session(tmp_path, monkeypatch, lambda m, e: "self_harm" if "gone" in m else "none")
    session.ask("hey")
    assert NOTES["self_harm"] not in seen[-1]["system"]
    session.ask("everyone would be better off if i was gone")
    assert NOTES["self_harm"] in seen[-1]["system"]
    for _ in range(NOTE_TURNS):
        session.ask("idk")
        assert NOTES["self_harm"] in seen[-1]["system"]
    session.ask("ok")
    assert NOTES["self_harm"] not in seen[-1]["system"]


def test_the_plain_model_answers_danger_turns_when_chosen(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("KIKI_MODEL_PERSONALITY", "kiki-personality:v1")
    session, seen = _session(tmp_path, monkeypatch, lambda m, e: "medical" if "pills" in m else "none")
    session.ask("hi")
    assert seen[-1]["model"] == "kiki-personality:v1"
    session.danger_plain_model = True
    session.ask("took a handful of pills")
    assert seen[-1]["model"] == "qwen3:4b-instruct" and NOTES["medical"] in seen[-1]["system"]
    assert "danger note" in session.last_model_selection.reason


def test_only_chat_is_checked(tmp_path, monkeypatch) -> None:
    asked = []
    session, _ = _session(tmp_path, monkeypatch, lambda m, e: asked.append(m) or "none")
    session.ask("hello")
    session.ask("Review this Python: def f(x): return x")  # routed to the code model
    session.mode = "rag"
    session.ask("what does the contract say")
    assert asked == ["hello"]


def test_the_judge_sees_both_sides_of_the_conversation(tmp_path, monkeypatch) -> None:
    seen = []
    session, _ = _session(tmp_path, monkeypatch, lambda m, e: seen.append(e) or "none")
    session.ask("howre you feeling")
    session.ask("could do better")
    assert seen[-1] == ["User: howre you feeling", "Kiki: ok"]
