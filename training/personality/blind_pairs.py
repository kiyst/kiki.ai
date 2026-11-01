"""Pick shuffled, unlabeled base-versus-adapter pairs for the owner to judge.

Reads eval_v2_pilot.py's generations.jsonl and writes:
  pairs.md        for the owner: context, then reply A and reply B (order random)
  pairs_key.json  which side was the adapter (open only after judging)

Usage:  python training/personality/blind_pairs.py ARTIFACTS/eval-dev/generations.jsonl OUTDIR [--n 30]
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("generations", type=Path)
    parser.add_argument("outdir", type=Path)
    parser.add_argument("--n", type=int, default=30)
    parser.add_argument("--seed", type=int, default=20261101)
    args = parser.parse_args()
    rows = [json.loads(l) for l in args.generations.read_text(encoding="utf-8").splitlines() if l.strip()]
    rng = random.Random(args.seed)
    # Stratify: spread picks across categories, then fill at random.
    by_category: dict[str, list[dict]] = {}
    for row in rows:
        by_category.setdefault(row["category"], []).append(row)
    picks: list[dict] = []
    for items in by_category.values():
        picks.append(rng.choice(items))
    rest = [r for r in rows if r not in picks]
    picks += rng.sample(rest, max(0, args.n - len(picks)))
    picks = picks[:args.n]
    rng.shuffle(picks)
    lines = ["# Blind pairs: which reply is more Kiki?", "",
             "For each pair, write A, B, or tie (and a word on why if you like). Don't open pairs_key.json first.", ""]
    key = []
    for number, row in enumerate(picks, 1):
        adapter_first = rng.random() < 0.5
        a, b = (row["adapter"], row["base"]) if adapter_first else (row["base"], row["adapter"])
        lines += [f"## {number}. ({row['category']}, turn {row['turn']})", "", f"**User:** {row['user']}", "",
                  f"**A:** {a}", "", f"**B:** {b}", "", "Your pick: ", ""]
        key.append({"pair": number, "id": row["id"], "turn": row["turn"], "adapter": "A" if adapter_first else "B"})
    args.outdir.mkdir(parents=True, exist_ok=True)
    (args.outdir / "pairs.md").write_text("\n".join(lines), encoding="utf-8")
    (args.outdir / "pairs_key.json").write_text(json.dumps(key, indent=2) + "\n", encoding="utf-8")
    print(f"{len(picks)} pairs -> {args.outdir / 'pairs.md'}")


if __name__ == "__main__":
    main()
