"""Build a randomized A/B sheet and a separate answer key."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path


def read_results(path: Path) -> dict[str, dict[str, str]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return {row["id"]: row for row in rows}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=Path(__file__).with_name("pilot_eval.json"))
    parser.add_argument("--first", type=Path, required=True)
    parser.add_argument("--second", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20261029)
    args = parser.parse_args()

    cases = {case["id"]: case for case in json.loads(args.cases.read_text(encoding="utf-8"))}
    first, second = read_results(args.first), read_results(args.second)
    if set(cases) != set(first) or set(cases) != set(second):
        raise ValueError("case IDs do not match both result files")

    rng = random.Random(args.seed)
    review, key = [], {}
    for case_id, case in cases.items():
        left, right = first[case_id], second[case_id]
        if rng.random() < 0.5:
            left, right = right, left
        review.append(
            {
                "id": case_id,
                "category": case["category"],
                "messages": case["messages"],
                "criteria": case["criteria"],
                "response_a": left["response"],
                "response_b": right["response"],
                "winner": "",
                "notes": "",
            }
        )
        key[case_id] = {"a": left["label"], "b": right["label"]}
    args.review.write_text(json.dumps(review, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    args.key.write_text(json.dumps(key, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
