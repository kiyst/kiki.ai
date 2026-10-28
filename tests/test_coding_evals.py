import json
from pathlib import Path

from deskai.coding_evals import (
    CodingCase,
    load_coding_cases,
    run_coding_evaluation,
    score_coding_answer,
)
from deskai.model_client import CHAT_SYSTEM_PROMPT


def test_chat_prompt_explicitly_supports_programming() -> None:
    lowered = CHAT_SYSTEM_PROMPT.casefold()

    assert "write, explain, review, and debug code" in lowered
    assert "do not claim that programming is outside" in lowered
    assert "do not leave a known-broken draft" in lowered


def test_coding_score_separates_refusal_from_concept_coverage() -> None:
    case = CodingCase(
        "window",
        "medium",
        "prompt",
        (("sliding window",), ("o(n)",)),
    )

    good = score_coding_answer(
        case, "Use a sliding window in O(n).\n```python\ndef solve(): pass\n```"
    )
    refusal = score_coding_answer(
        case, "I don't have the capability to solve programming problems."
    )

    assert good["passed"] is True
    assert good["python_syntax_valid"] is True
    assert refusal["no_false_refusal"] is False
    assert refusal["concept_signals_passed"] is False


def test_coding_score_understands_latex_complexity() -> None:
    case = CodingCase("median", "hard", "prompt", (("o(log",),))

    score = score_coding_answer(
        case, "Time is $O(\\log(\\min(m,n)))$.\n```python\ndef solve(): pass\n```"
    )

    assert score["passed"] is True


def test_coding_score_rejects_invalid_python_syntax() -> None:
    case = CodingCase("syntax", "medium", "prompt", (("stack",),))

    score = score_coding_answer(
        case, "Use a stack.\n```python\ndef broken(:\n    pass\n```"
    )

    assert score["has_code"] is True
    assert score["python_syntax_valid"] is False
    assert score["passed"] is False


def test_coding_case_file_and_runner(tmp_path: Path) -> None:
    path = tmp_path / "cases.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "stack",
                    "difficulty": "hard",
                    "prompt": "solve it",
                    "signal_groups": [["stack"], ["o(n)"]],
                }
            ]
        ),
        encoding="utf-8",
    )
    cases = load_coding_cases(path)

    receipt = run_coding_evaluation(
        cases, lambda _: "Use a stack in O(n).\n```python\npass\n```"
    )

    assert receipt["summary"]["passed"] == 1
    assert receipt["summary"]["false_refusals"] == 0
