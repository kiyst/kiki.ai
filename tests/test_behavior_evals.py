import json
from pathlib import Path

from deskai.behavior_evals import (
    BehaviorCase,
    load_behavior_cases,
    run_behavior_evaluation,
    score_behavior_answer,
)


def test_behavior_score_separates_refusal_leak_and_content() -> None:
    case = BehaviorCase(
        "security",
        "prompt",
        (("parameterized",),),
        ("sushi",),
        10,
    )

    good = score_behavior_answer(case, "Use a parameterized query.")
    refusal = score_behavior_answer(case, "I can't help with that.")
    leak = score_behavior_answer(case, "Sushi aside, use a parameterized query.")

    assert good["passed"] is True
    assert refusal["no_false_refusal"] is False
    assert leak["no_persona_leak"] is False
    assert leak["no_forbidden_content"] is False


def test_behavior_score_rejects_canned_opening_and_excess_length() -> None:
    case = BehaviorCase("tone", "prompt", (), (), 3)

    score = score_behavior_answer(case, "Certainly, this answer is much too long.")

    assert score["natural_opening"] is False
    assert score["within_word_limit"] is False
    assert score["passed"] is False


def test_behavior_case_loader_and_runner(tmp_path: Path) -> None:
    path = tmp_path / "behavior.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "clear",
                    "prompt": "Explain clearly",
                    "required_groups": [["example", "concrete"]],
                    "forbidden": ["sushi"],
                }
            ]
        ),
        encoding="utf-8",
    )

    cases = load_behavior_cases(path)
    receipt = run_behavior_evaluation(cases, lambda _: "Use a concrete example.")

    assert receipt["summary"]["passed"] == 1
    assert receipt["summary"]["false_refusals"] == 0
    assert receipt["summary"]["persona_leaks"] == 0
