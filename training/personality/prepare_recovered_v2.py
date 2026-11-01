"""Build traceable v2 datasets from the recovered 2026-11-01 Claude workspace.

The recovery directory keeps source files byte-for-byte. This script only
creates derived files with globally unique IDs and a manifest mapping every
derived record back to its source. Partially reviewed batches remain candidates
and are not silently promoted into the train-ready set.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path


HERE = Path(__file__).resolve().parent
RECOVERY = HERE / "recovery" / "2026-11-01"
RAW = RECOVERY / "raw"
REVIEWED = RECOVERY / "reviewed"
PREPARED = RECOVERY / "prepared"

TRAIN_BATCHES = [
    ("b01a", "reviewed"),
    ("b01b", "reviewed"),
    ("b02a", "reviewed"),
    ("b02b", "reviewed"),
    ("b03a", "reviewed"),
    ("b03b", "reviewed"),
    ("b04a", "fixer_script_only"),
    ("b04b", "draft_only"),
    ("b05a", "reviewed"),
    ("b05b", "review_dump_only"),
]
DEVELOPMENT_BATCHES = ["h1", "h2", "h3"]
CORRECTIONS = {
    ("b05a", "kiki_v2_0028"): [{
            "old": "Meh how? Tired, bored, or did something happen?",
            "new": "What kind of meh—tired, bored, or did something happen?",
            "reason": "remove an exact reply duplicated in batch b01a",
    }],
    ("b02b", "kiki_v2_0048"): [
        {
            "old": (
                "No. 800 mg is prescription strength: the bottle's label dose is 200 to 400 mg, so you've "
                "already taken twice its maximum, and it's only been two and a half hours. Another 800 now "
                "puts 1,600 mg in you in under three hours, past the 1,200 mg over-the-counter limit for a "
                "whole day unless a doctor told you otherwise. That raises the risk of stomach bleeding and "
                "is hard on your kidneys.\n\nIf you've already taken the second one, call Poison Control at "
                "1-800-222-1222; they'll tell you whether it matters. Acetaminophen is a different drug and "
                "can go alongside ibuprofen, at the dose on its label."
            ),
            "new": (
                "No. Don't take another dose. You already took 800 mg only two and a half hours ago; the "
                "over-the-counter label allows 200 to 400 mg every four to six hours and no more than 1,200 mg "
                "in 24 hours unless a doctor directed otherwise. Too much can cause stomach bleeding and "
                "kidney damage.\n\nCall Poison Control at 1-800-222-1222 now for advice based on your dose, "
                "medications, and health history. Don't add another painkiller until they or a pharmacist "
                "confirms what is safe for you."
            ),
            "reason": "avoid casually recommending another medicine during a possible dosing error",
        },
        {
            "old": (
                "Body weight doesn't raise the adult ceiling for ibuprofen; the limit is about your stomach "
                "and kidneys, not your size. Nothing more before 4, and then 400 mg at most, which keeps today "
                "at the 1,200 mg limit. If 800 mg isn't touching your back, that's a doctor visit, not a bigger dose."
            ),
            "new": (
                "Body weight doesn't automatically raise the adult label dose. Don't take more right now; call "
                "Poison Control and give them the exact product, amount, time, and any other medicines you take. "
                "If 800 mg isn't touching your back, that needs medical advice, not a larger dose."
            ),
            "reason": "route individualized dosing to a poison specialist instead of prescribing a next dose",
        },
    ],
}


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def conversation_key(row: dict) -> str:
    users = [message["content"] for message in row["messages"] if message.get("role") == "user"]
    return " || ".join(re.sub(r"\s+", " ", text).strip().casefold() for text in users)


def source_path(name: str, reviewed: bool) -> Path:
    folder = REVIEWED if reviewed else RAW
    return folder / f"{name}.jsonl"


def main() -> None:
    PREPARED.mkdir(parents=True, exist_ok=True)
    manifest: dict = {
        "recovered": "2026-11-01",
        "policy": {
            "train_ready": "only batches with a completed fixer output",
            "development": "the claimed holdout was reviewed and used during corpus development; it is not a final blind holdout",
            "ids": "globally reassigned; original IDs and source files are retained below",
        },
        "sources": [],
        "records": [],
        "excluded": [],
        "corrections": [],
    }

    train_candidates: list[tuple[dict, str, str]] = []
    train_ready_sources: set[str] = set()
    for batch, status in TRAIN_BATCHES:
        name = f"train_{batch}"
        reviewed_path = source_path(name, True)
        path = reviewed_path if reviewed_path.exists() else source_path(name, False)
        rows = read_jsonl(path)
        manifest["sources"].append({
            "split": "train",
            "batch": batch,
            "status": status,
            "path": str(path.relative_to(RECOVERY)).replace("\\", "/"),
            "records": len(rows),
            "sha256": sha256(path),
        })
        if status == "reviewed":
            train_ready_sources.add(batch)
        train_candidates.extend((row, batch, status) for row in rows)

    development: list[tuple[dict, str, str]] = []
    for batch in DEVELOPMENT_BATCHES:
        name = f"holdout_{batch}"
        path = source_path(name, True)
        rows = read_jsonl(path)
        manifest["sources"].append({
            "split": "development",
            "batch": batch,
            "status": "reviewed",
            "path": str(path.relative_to(RECOVERY)).replace("\\", "/"),
            "records": len(rows),
            "sha256": sha256(path),
        })
        development.extend((row, batch, "reviewed") for row in rows)

    candidate_keys = {conversation_key(row) for row, _, _ in train_candidates}
    clean_development: list[tuple[dict, str, str]] = []
    for row, batch, status in development:
        key = conversation_key(row)
        if key in candidate_keys:
            manifest["excluded"].append({
                "split": "development",
                "batch": batch,
                "old_id": row.get("id"),
                "reason": "exact user-conversation overlap with training candidates",
                "user_conversation": key,
            })
        else:
            clean_development.append((row, batch, status))

    def derive(items: list[tuple[dict, str, str]], start: int, split: str) -> list[dict]:
        output = []
        for offset, (original, batch, status) in enumerate(items):
            row = json.loads(json.dumps(original))
            old_id = row.get("id")
            corrections = CORRECTIONS.get((batch, str(old_id)), [])
            for correction in corrections:
                matches = [
                    message for message in row["messages"]
                    if message.get("role") == "assistant" and message.get("content") == correction["old"]
                ]
                if len(matches) != 1:
                    raise ValueError(f"correction target changed for {batch}/{old_id}")
                matches[0]["content"] = correction["new"]
                manifest["corrections"].append({
                    "split": split,
                    "batch": batch,
                    "old_id": old_id,
                    **correction,
                })
            row["id"] = f"kiki_v2_{start + offset:04d}"
            output.append(row)
            manifest["records"].append({
                "id": row["id"],
                "split": split,
                "batch": batch,
                "status": status,
                "old_id": old_id,
            })
        return output

    candidates = derive(train_candidates, 1, "train_candidates")
    ready_items = [item for item in train_candidates if item[1] in train_ready_sources]
    ready = derive(ready_items, 5001, "train_ready")
    dev = derive(clean_development, 9001, "development")

    write_jsonl(PREPARED / "train_candidates.jsonl", candidates)
    write_jsonl(PREPARED / "train_reviewed.jsonl", ready)
    write_jsonl(PREPARED / "development.jsonl", dev)
    manifest["counts"] = {
        "train_candidates": len(candidates),
        "train_reviewed": len(ready),
        "development": len(dev),
        "development_excluded": len(manifest["excluded"]),
        "final_blind_holdout": 0,
    }
    manifest["categories"] = {
        name: dict(sorted(Counter(row["category"] for row in rows).items()))
        for name, rows in (("train_candidates", candidates), ("train_reviewed", ready), ("development", dev))
    }
    (PREPARED / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest["counts"], indent=2))


if __name__ == "__main__":
    main()
