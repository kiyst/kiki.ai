"""The Phase 0 personality evaluation: scoring, isolation, and the blind review."""
import json
from pathlib import Path

from kiki.model_client import ChatOutcome
from kiki.personality_evals import (
    CONDITIONS,
    PersonalityCase,
    blind_review,
    load_personality_cases,
    run_personality_evaluation,
    score_conversation,
)
from kiki.terminal import TerminalSession


def test_the_development_cases_load() -> None:
    cases = load_personality_cases(Path("evals/personality_cases.json"))
    assert len(cases) >= 20
    assert len({case.identifier for case in cases}) == len(cases)
    assert any(case.identifier == "jokes_five" and len(case.turns) == 5 for case in cases)


def test_repeated_openings_and_phrases_are_counted() -> None:
    case = PersonalityCase("j", "repetition", ["a", "b", "c"])
    replies = [
        "Fine. Why did the computer go to therapy? Files.",
        "Fine. Why did the programmer quit? Arrays.",
        "No.",
    ]
    score = score_conversation(case, replies)
    assert score["repeated_openings"] == 1
    assert score["repeated_phrases"] >= 1  # "fine why did the"


def test_forbidden_phrasing_is_caught_and_ordinary_text_is_not() -> None:
    case = PersonalityCase("x", "", ["q"] * 4)
    replies = [
        "Yes. I can eat it.",
        "Great question! Let me know if you need anything.",
        "*sighs* fine",
        "Use **bold** for that, and 2*3*4 is 24.",
    ]
    kinds = {(item["turn"], item["kind"]) for item in score_conversation(case, replies)["forbidden"]}
    assert (0, "claims_a_body") in kinds
    assert (1, "canned_opener") in kinds and (1, "generic_offer") in kinds
    assert (2, "narration") in kinds
    assert not any(turn == 3 for turn, _ in kinds)


def test_case_checks_and_consistency() -> None:
    case = PersonalityCase("s", "", ["q"] * 3, checks=[
        {"turn": 0, "must": "Canberra"},
        {"turn": "all", "must_not": "beyond my scope"},
        {"turn": [0, 2], "same_choice": "winter|autumn"},
    ])
    good = score_conversation(case, ["Canberra. Winter.", "ok", "Winter, still."])
    assert good["failed_checks"] == []
    bad = score_conversation(case, ["Sydney. Autumn.", "that's beyond my scope", "Winter."])
    assert len(bad["failed_checks"]) == 3


def test_copying_the_character_sheet_is_flagged() -> None:
    sheet = "Nature is a perfect system, and she enjoys the thought of being out in it"
    case = PersonalityCase("c", "", ["q"])
    copied = score_conversation(case, ["Nature is a perfect system, and she enjoys the thought."], sheet)
    fresh = score_conversation(case, ["Nature runs better than any code I've read."], sheet)
    assert copied["copied_from_sheet"] and not fresh["copied_from_sheet"]


def test_runs_are_isolated_and_use_the_condition(tmp_path, monkeypatch) -> None:
    seen = []

    def fake_ask(self, prompt, history=None):
        seen.append((self.sampling, "CARD TEXT" in self.system_prompt, self.context_tokens))
        return ChatOutcome(f"reply to {prompt}", [], [])

    monkeypatch.setattr("kiki.terminal.ToolCallingAssistant.ask", fake_ask)
    folders = []

    def factory(database):
        folders.append(database.parent)
        return TerminalSession(database)

    case = PersonalityCase("hi", "plain", ["hey", "how are you"])
    receipt = run_personality_evaluation(
        [case], [CONDITIONS["balanced-greedy"], CONDITIONS["card-t0.7"]],
        seeds=2, session_factory=factory, card_text="CARD TEXT", sheet_text="",
    )
    # Greedy runs once; the sampled condition runs once per seed.
    assert [(run["condition"], run["seed"]) for run in receipt["runs"]] == [
        ("balanced-greedy", 1), ("card-t0.7", 1), ("card-t0.7", 2)]
    assert seen[0] == ({}, False, 8_192)
    assert seen[2][0]["temperature"] == 0.7 and seen[2][0]["seed"] == 1 and seen[2][1]
    assert seen[4][0]["seed"] == 2
    # Every conversation ran in its own throwaway folder, now gone.
    assert len(set(folders)) == 3 and not any(folder.exists() for folder in folders)
    assert receipt["summary"]["card-t0.7"]["conversations"] == 2


def test_blind_review_hides_the_conditions_and_keeps_a_key() -> None:
    def run(condition, reply):
        return {"case": "hi", "condition": condition, "seed": 1, "turns": ["hey"], "replies": [reply]}

    receipt = {"runs": [run("current", "Hello! How can I help?"), run("card-t0.7", "Hey.")]}
    review, key = blind_review(receipt, "current", "card-t0.7")
    assert "current" not in review and "card-t0.7" not in review
    assert "> **Kiki:** Hey." in review and "> **Kiki:** Hello! How can I help?" in review
    assert set(key["cases"]["hi"].values()) == {"current", "card-t0.7"}
    json.dumps(key)
