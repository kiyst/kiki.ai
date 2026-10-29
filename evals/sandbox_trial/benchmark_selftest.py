"""Grade every benchmark's reference solution in the sandbox; all should pass.

Separates harness or sandbox problems from model failures.
"""

import json
import sys
import time

from coding_benchmark import RECEIPTS, grade, load


def reference(benchmark: str, problem: dict) -> str:
    if benchmark == "humaneval":
        return problem["prompt"] + problem["canonical_solution"]
    if benchmark == "mbpp":
        return problem["canonical_solution"]
    return problem["completion"]


def main() -> None:
    report = {}
    for benchmark in sys.argv[1:] or ["humaneval", "mbpp", "leetcode"]:
        problems = load(benchmark)
        failures = []
        started = time.perf_counter()
        for problem in problems:
            outcome = grade(benchmark, problem, reference(benchmark, problem))
            if not outcome.get("passed"):
                failures.append({"id": problem["task_id"], "error": outcome.get("error")})
                print(benchmark, problem["task_id"], outcome.get("error"), flush=True)
        report[benchmark] = {
            "problems": len(problems),
            "reference_passed": len(problems) - len(failures),
            "failures": failures,
            "seconds": round(time.perf_counter() - started),
        }
        print(benchmark, json.dumps({k: v for k, v in report[benchmark].items() if k != "failures"}), flush=True)
    RECEIPTS.mkdir(parents=True, exist_ok=True)
    (RECEIPTS / "reference-selftest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
