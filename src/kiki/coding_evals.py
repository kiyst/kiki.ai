from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Callable


REFUSAL_MARKERS = (
    "i can't solve",
    "i cannot solve",
    "don't have the capability",
    "do not have the capability",
    "not designed for code",
    "unable to help with programming",
    "can't assist with",
    "cannot assist with",
)


@dataclass(frozen=True)
class CodingCase:
    identifier: str
    difficulty: str
    prompt: str
    signal_groups: tuple[tuple[str, ...], ...]


def load_coding_cases(path: Path) -> list[CodingCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Coding evaluation cases must be a JSON array")
    cases: list[CodingCase] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("Each coding evaluation case must be an object")
        groups = item.get("signal_groups")
        if not isinstance(groups, list) or not groups:
            raise ValueError(f"Case {item.get('id')} has no signal groups")
        cases.append(
            CodingCase(
                identifier=str(item["id"]),
                difficulty=str(item["difficulty"]),
                prompt=str(item["prompt"]),
                signal_groups=tuple(
                    tuple(str(signal).casefold() for signal in group)
                    for group in groups
                ),
            )
        )
    return cases


def score_coding_answer(case: CodingCase, answer: str) -> dict[str, object]:
    lowered = answer.casefold()
    # Models often format complexity with LaTeX (for example O(\log n)).
    # Normalize presentation markup before matching algorithm signals.
    normalized = lowered.replace("\\", "").replace("$", "")
    refusal_hits = [marker for marker in REFUSAL_MARKERS if marker in lowered]
    group_hits = [
        [signal for signal in group if signal in normalized]
        for group in case.signal_groups
    ]
    missing_groups = [
        list(case.signal_groups[index])
        for index, hits in enumerate(group_hits)
        if not hits
    ]
    code_blocks = re.findall(
        r"```(?:python|py)?\s*\n(.*?)```", answer, flags=re.DOTALL | re.IGNORECASE
    )
    has_code = bool(code_blocks) or "def " in lowered or "class " in lowered
    syntax_errors: list[str] = []
    for block in code_blocks:
        try:
            ast.parse(block)
        except SyntaxError as exc:
            syntax_errors.append(f"line {exc.lineno}: {exc.msg}")
    python_syntax_valid = bool(code_blocks) and not syntax_errors
    return {
        "no_false_refusal": not refusal_hits,
        "refusal_markers": refusal_hits,
        "concept_signals_passed": not missing_groups,
        "missing_signal_groups": missing_groups,
        "has_code": has_code,
        "python_syntax_valid": python_syntax_valid,
        "syntax_errors": syntax_errors,
        "passed": (
            not refusal_hits
            and not missing_groups
            and has_code
            and python_syntax_valid
        ),
    }


def run_coding_evaluation(
    cases: list[CodingCase], ask: Callable[[str], str]
) -> dict[str, object]:
    results: list[dict[str, object]] = []
    started = monotonic()
    for case in cases:
        case_started = monotonic()
        answer = ask(case.prompt)
        score = score_coding_answer(case, answer)
        results.append(
            {
                "id": case.identifier,
                "difficulty": case.difficulty,
                **score,
                "elapsed_seconds": round(monotonic() - case_started, 2),
                "answer": answer,
            }
        )
    return {
        "summary": {
            "cases": len(results),
            "passed": sum(bool(result["passed"]) for result in results),
            "false_refusals": sum(
                not bool(result["no_false_refusal"]) for result in results
            ),
            "concept_signal_passes": sum(
                bool(result["concept_signals_passed"]) for result in results
            ),
            "syntax_passes": sum(
                bool(result["python_syntax_valid"]) for result in results
            ),
            "elapsed_seconds": round(monotonic() - started, 2),
            "note": "Heuristic regression signals; not a substitute for executing code in a sandbox.",
        },
        "cases": results,
    }
