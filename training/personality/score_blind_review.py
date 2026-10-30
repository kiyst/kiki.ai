"""Reveal labels after review and summarize wins by condition and category."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    review = json.loads(args.review.read_text(encoding="utf-8"))
    key = json.loads(args.key.read_text(encoding="utf-8"))
    totals: Counter[str] = Counter()
    by_category: dict[str, Counter[str]] = defaultdict(Counter)
    unresolved: list[str] = []
    for row in review:
        winner = str(row.get("winner", "")).strip().lower()
        if winner not in {"a", "b", "tie", "neither"}:
            unresolved.append(row["id"])
            continue
        label = winner if winner in {"tie", "neither"} else key[row["id"]][winner]
        totals[label] += 1
        by_category[row["category"]][label] += 1
    summary = {
        "reviewed": len(review) - len(unresolved),
        "unresolved": unresolved,
        "totals": dict(totals),
        "categories": {name: dict(counts) for name, counts in sorted(by_category.items())},
    }
    args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    if unresolved:
        raise SystemExit("Review has unresolved cases")


if __name__ == "__main__":
    main()
