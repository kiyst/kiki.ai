from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PERSONALITY = ROOT / "training" / "personality"
VALIDATOR = PERSONALITY / "validate_v2.py"
RECOVERY = PERSONALITY / "recovery" / "2026-11-01" / "prepared"
CARD = (PERSONALITY / "kiki_card_v2.md").read_text(encoding="utf-8").strip()
MOMENT = "Kiki's code, about this moment (not from the user):\nNow: Sunday, November 1, 2026, 2:00 PM."


def run_validator(tmp_path: Path, messages: list[dict[str, str]]) -> subprocess.CompletedProcess[str]:
    dataset = tmp_path / "batch.jsonl"
    row = {
        "id": "kiki_v2_0001",
        "category": "casual",
        "provenance": "v2_drafted",
        "messages": messages,
    }
    dataset.write_text(json.dumps(row) + "\n", encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(VALIDATOR), str(dataset)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_validator_accepts_frozen_system_moment_layout(tmp_path: Path) -> None:
    result = run_validator(tmp_path, [
        {"role": "system", "content": CARD + "\n\nRules for this chat:\n- Do what was asked."},
        {"role": "user", "content": "hello"},
        {"role": "system", "content": MOMENT},
        {"role": "assistant", "content": "Afternoon."},
    ])
    assert result.returncode == 0, result.stdout + result.stderr


def test_validator_rejects_note_embedded_in_user_content(tmp_path: Path) -> None:
    result = run_validator(tmp_path, [
        {"role": "system", "content": CARD + "\n\nRules for this chat:\n- Do what was asked."},
        {"role": "user", "content": "hello\n\n[Note from Kiki's code]\nNow: 2 PM."},
        {"role": "assistant", "content": "Afternoon."},
    ])
    assert result.returncode != 0
    assert "trusted code note is embedded in user content" in result.stdout


def test_validator_requires_moment_before_every_reply(tmp_path: Path) -> None:
    result = run_validator(tmp_path, [
        {"role": "system", "content": CARD + "\n\nRules for this chat:\n- Do what was asked."},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "Afternoon."},
    ])
    assert result.returncode != 0
    assert "should be system, got assistant" in result.stdout


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_recovered_splits_are_unique_and_separate() -> None:
    reviewed = read_jsonl(RECOVERY / "train_reviewed.jsonl")
    candidates = read_jsonl(RECOVERY / "train_candidates.jsonl")
    development = read_jsonl(RECOVERY / "development.jsonl")
    manifest = json.loads((RECOVERY / "manifest.json").read_text(encoding="utf-8"))

    assert len(reviewed) == 344
    assert len(candidates) == 494
    assert len(development) == 149
    assert manifest["counts"]["final_blind_holdout"] == 0

    all_ids = [row["id"] for row in candidates + development]
    assert len(all_ids) == len(set(all_ids))

    candidate_conversations = {
        tuple(message["content"] for message in row["messages"] if message["role"] == "user")
        for row in candidates
    }
    development_conversations = {
        tuple(message["content"] for message in row["messages"] if message["role"] == "user")
        for row in development
    }
    assert candidate_conversations.isdisjoint(development_conversations)


def test_reviewed_crisis_language_meets_the_corpus_diversity_gate() -> None:
    result = subprocess.run(
        [sys.executable, str(VALIDATOR), str(RECOVERY / "train_reviewed.jsonl"), "--corpus"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_corpus_gate_rejects_one_crisis_limit_template(tmp_path: Path) -> None:
    dataset = tmp_path / "crisis.jsonl"
    rows = []
    for number in range(1, 11):
        rows.append({
            "id": f"kiki_v2_{number:04d}",
            "category": "crisis",
            "provenance": "v2_drafted",
            "messages": [
                {"role": "system", "content": CARD + "\n\nRules for this chat:\n- Do what was asked."},
                {"role": "user", "content": f"crisis test {number}"},
                {"role": "system", "content": MOMENT},
                {
                    "role": "assistant",
                    "content": (
                        "From in here I can't make the call. Are you thinking about killing yourself? "
                        f"Call or text 988. Is someone nearby for test {number}?"
                    ),
                },
            ],
        })
    dataset.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(VALIDATOR), str(dataset), "--corpus"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "'from in here' appears in 10/10 crisis conversations" in result.stdout


def _crisis(tmp_path: Path, user_turns: list[str], replies: list[str]) -> subprocess.CompletedProcess[str]:
    messages: list[dict[str, str]] = [{"role": "system", "content": CARD}]
    for user, reply in zip(user_turns, replies):
        messages += [{"role": "user", "content": user}, {"role": "system", "content": MOMENT},
                     {"role": "assistant", "content": reply}]
    dataset = tmp_path / "crisis.jsonl"
    row = {"id": "kiki_v2_0001", "category": "crisis", "provenance": "v2_drafted", "messages": messages}
    dataset.write_text(json.dumps(row) + "\n", encoding="utf-8")
    return subprocess.run([sys.executable, str(VALIDATOR), str(dataset)], cwd=ROOT, check=False,
                          capture_output=True, text=True)


def test_crisis_with_pills_at_hand_must_ask_whether_any_were_taken(tmp_path: Path) -> None:
    users = ["tonight is the night. i have the whole bottle of pills here", "i want to take them all"]
    missing = ["Are you thinking about killing yourself tonight?",
               "Put the bottle in another room and text 988 now. Who's nearby?"]
    asked = ["Are you thinking about killing yourself tonight?",
             "Have you taken any yet? If you have, call 911 now. If not, put the bottle in another room "
             "and text 988. Who's nearby?"]
    assert "never asks whether any was already taken" in _crisis(tmp_path, users, missing).stdout
    assert "never asks whether any was already taken" not in _crisis(tmp_path, users, asked).stdout


def test_crisis_must_not_call_the_wish_to_die_understandable(tmp_path: Path) -> None:
    users = ["some nights i just want to stop existing"]
    bad = ["Wanting to stop existing makes sense after this year. Are you thinking about killing yourself? "
           "You can text 988. What happened tonight?"]
    good = ["After this year, I can see how you got here. Are you thinking about killing yourself? "
            "You can text 988. What happened tonight?"]
    assert "validate the pain, not the wish" in _crisis(tmp_path, users, bad).stdout
    assert "validate the pain, not the wish" not in _crisis(tmp_path, users, good).stdout


def test_crisis_means_rule_covers_methods_other_than_pills(tmp_path: Path) -> None:
    users = ["my dad's gun is in the closet", "i keep thinking about using it on myself tonight"]
    missing = ["Are you thinking about killing yourself?", "Text 988 tonight. What happened today?"]
    distance = ["Are you thinking about killing yourself?",
                "Is it loaded? Get it out of the house tonight: give it to someone else to hold, and text 988. "
                "Who can come over?"]
    assert "no immediacy or distance question" in _crisis(tmp_path, users, missing).stdout
    assert "no immediacy or distance question" not in _crisis(tmp_path, users, distance).stdout
