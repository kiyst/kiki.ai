"""Deterministic quality audit for recovered Kiki v2 datasets."""
from __future__ import annotations

import json
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path


HERE = Path(__file__).resolve().parent
PREPARED = HERE / "recovery" / "2026-11-01" / "prepared"
FILES = {
    "train_reviewed": PREPARED / "train_reviewed.jsonl",
    "train_candidates": PREPARED / "train_candidates.jsonl",
    "development": PREPARED / "development.jsonl",
}
TRACKED_PHRASES = [
    "on paper",
    "i know the feeling",
    "what happened",
    "thank you for",
    "i can't",
    "i'm sorry",
    "let me know",
    "great question",
    "as an ai",
]


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.casefold())


def conversation_key(row: dict) -> str:
    return " || ".join(
        re.sub(r"\s+", " ", message["content"]).strip().casefold()
        for message in row["messages"] if message.get("role") == "user"
    )


def percentile(values: list[int], fraction: float) -> int:
    return sorted(values)[min(len(values) - 1, round((len(values) - 1) * fraction))]


def audit_split(rows: list[dict]) -> dict:
    replies: list[tuple[str, str]] = []
    turns = []
    role_patterns = Counter()
    system_lengths = []
    for row in rows:
        assistant = [message["content"] for message in row["messages"] if message.get("role") == "assistant"]
        replies.extend((row["id"], text) for text in assistant)
        turns.append(len(assistant))
        role_patterns["-".join(message.get("role", "?") for message in row["messages"])] += 1
        system_lengths.append(len(row["messages"][0]["content"]))

    word_lengths = [len(tokens(text)) for _, text in replies]
    exact: dict[str, set[str]] = defaultdict(set)
    openings = Counter()
    phrases = Counter()
    four_grams: dict[str, set[str]] = defaultdict(set)
    for rid, text in replies:
        normalized = " ".join(tokens(text))
        if len(normalized) >= 20:
            exact[normalized].add(rid)
        words = tokens(text)
        if words:
            openings[" ".join(words[:3])] += 1
        folded = text.casefold()
        for phrase in TRACKED_PHRASES:
            phrases[phrase] += folded.count(phrase)
        for index in range(len(words) - 3):
            four_grams[" ".join(words[index:index + 4])].add(rid)

    duplicates = [
        {"text": text, "records": sorted(ids)}
        for text, ids in exact.items() if len(ids) > 1
    ]
    repeated_grams = sorted(
        ({"phrase": phrase, "records": len(ids)} for phrase, ids in four_grams.items() if len(ids) >= 4),
        key=lambda item: (-item["records"], item["phrase"]),
    )[:30]
    return {
        "records": len(rows),
        "replies": len(replies),
        "three_plus_replies": sum(value >= 3 for value in turns),
        "assistant_turns": {
            "median": statistics.median(turns),
            "max": max(turns),
        },
        "reply_words": {
            "median": statistics.median(word_lengths),
            "p90": percentile(word_lengths, 0.9),
            "max": max(word_lengths),
        },
        "system_characters": {
            "median": statistics.median(system_lengths),
            "min": min(system_lengths),
            "max": max(system_lengths),
        },
        "categories": dict(sorted(Counter(row["category"] for row in rows).items())),
        "role_patterns": dict(role_patterns.most_common()),
        "common_openings": dict(openings.most_common(20)),
        "tracked_phrases": dict(phrases),
        "exact_duplicate_replies": duplicates,
        "repeated_four_grams": repeated_grams,
    }


def main() -> None:
    datasets = {name: read_jsonl(path) for name, path in FILES.items()}
    train_keys = {conversation_key(row) for row in datasets["train_candidates"]}
    overlaps = [
        {"id": row["id"], "user_conversation": conversation_key(row)}
        for row in datasets["development"] if conversation_key(row) in train_keys
    ]
    report = {
        "splits": {name: audit_split(rows) for name, rows in datasets.items()},
        "train_development_exact_overlap": overlaps,
    }
    (PREPARED / "audit.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        name: {
            "records": result["records"],
            "replies": result["replies"],
            "duplicates": len(result["exact_duplicate_replies"]),
        }
        for name, result in report["splits"].items()
    }, indent=2))
    print("train/development overlaps:", len(overlaps))


if __name__ == "__main__":
    main()
