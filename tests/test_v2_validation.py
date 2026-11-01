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
