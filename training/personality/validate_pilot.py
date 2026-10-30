"""Validate the frozen training corpus and novel pilot evaluation set."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def main() -> None:
    train = [
        json.loads(line)
        for line in (HERE / "kiki_personality_v1.review.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]
    evaluation = json.loads((HERE / "pilot_eval.json").read_text(encoding="utf-8"))
    errors: list[str] = []
    train_prompts = {
        normalize(message["content"])
        for row in train
        for message in row["messages"]
        if message["role"] == "user"
    }
    seen: set[str] = set()
    categories: Counter[str] = Counter()
    for case in evaluation:
        case_id = case.get("id", "<missing>")
        messages = case.get("messages")
        categories[case.get("category", "<missing>")] += 1
        if not isinstance(messages, list) or not messages:
            errors.append(f"{case_id}: messages missing")
            continue
        if messages[-1].get("role") != "user":
            errors.append(f"{case_id}: conversation must end with user")
        if not case.get("criteria"):
            errors.append(f"{case_id}: criteria missing")
        prompt = normalize(messages[-1].get("content", ""))
        if not prompt:
            errors.append(f"{case_id}: empty final prompt")
        if prompt in train_prompts:
            errors.append(f"{case_id}: final prompt duplicates training data")
        if prompt in seen:
            errors.append(f"{case_id}: duplicate evaluation prompt")
        seen.add(prompt)
    if len(train) != 500:
        errors.append(f"expected 500 training rows, found {len(train)}")
    if len(evaluation) != 60:
        errors.append(f"expected 60 evaluation cases, found {len(evaluation)}")
    print(f"training records: {len(train)}")
    print(f"evaluation cases: {len(evaluation)}")
    print("evaluation categories:")
    for category, count in sorted(categories.items()):
        print(f"  {category}: {count}")
    if errors:
        print("errors:")
        for error in errors:
            print(f"  - {error}")
        raise SystemExit(1)
    print("validation: passed")


if __name__ == "__main__":
    main()
