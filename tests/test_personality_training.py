from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from kiki.personality import PersonalitySettings, personality_prompt


ROOT = Path(__file__).resolve().parents[1]
PERSONALITY = ROOT / "training" / "personality"


def test_frozen_personality_corpus_and_eval_validate() -> None:
    result = subprocess.run(
        [sys.executable, str(PERSONALITY / "validate_pilot.py")],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "training records: 500" in result.stdout
    assert "evaluation cases: 60" in result.stdout


def test_eval_cases_have_review_criteria_and_end_with_user() -> None:
    cases = json.loads((PERSONALITY / "pilot_eval.json").read_text(encoding="utf-8"))
    assert len(cases) == 60
    assert len({case["id"] for case in cases}) == len(cases)
    for case in cases:
        assert case["criteria"]
        assert case["messages"][-1]["role"] == "user"


def test_frozen_pilot_prompt_matches_runtime_default() -> None:
    frozen = (PERSONALITY / "pilot_system_prompt.txt").read_text(encoding="utf-8").strip()
    assert frozen == personality_prompt(PersonalitySettings())


def test_cloud_entry_points_parse_help_without_cloud_dependencies() -> None:
    for script in (
        "train_qlora.py",
        "run_inference.py",
        "build_blind_review.py",
        "score_blind_review.py",
        "merge_adapter.py",
    ):
        result = subprocess.run(
            [sys.executable, str(PERSONALITY / script), "--help"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"{script}: {result.stdout}{result.stderr}"


def test_blind_review_builder_and_scorer(tmp_path: Path) -> None:
    cases = [
        {
            "id": "one",
            "category": "casual",
            "messages": [{"role": "user", "content": "Hello"}],
            "criteria": ["brief"],
        }
    ]
    cases_path = tmp_path / "cases.json"
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    review = tmp_path / "review.json"
    key = tmp_path / "key.json"
    summary = tmp_path / "summary.json"
    cases_path.write_text(json.dumps(cases), encoding="utf-8")
    first.write_text('{"id":"one","label":"base","response":"A"}\n', encoding="utf-8")
    second.write_text('{"id":"one","label":"adapter","response":"B"}\n', encoding="utf-8")

    subprocess.run(
        [
            sys.executable,
            str(PERSONALITY / "build_blind_review.py"),
            "--cases",
            str(cases_path),
            "--first",
            str(first),
            "--second",
            str(second),
            "--review",
            str(review),
            "--key",
            str(key),
        ],
        check=True,
    )
    rows = json.loads(review.read_text(encoding="utf-8"))
    rows[0]["winner"] = "a"
    review.write_text(json.dumps(rows), encoding="utf-8")
    subprocess.run(
        [
            sys.executable,
            str(PERSONALITY / "score_blind_review.py"),
            "--review",
            str(review),
            "--key",
            str(key),
            "--output",
            str(summary),
        ],
        check=True,
    )
    scored = json.loads(summary.read_text(encoding="utf-8"))
    assert scored["reviewed"] == 1
    assert sum(scored["totals"].values()) == 1
