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

# The first recovered drafts followed one owner-written crisis example too
# literally: 14 of 15 reviewed crisis conversations repeated "from in here".
# Keep a few natural uses of that phrasing, but vary or omit the operational
# limitation when it is not needed for the next safety step. The direct
# question, means reduction, human connection, and one fitted 988 offer remain
# unchanged. Raw sources stay byte-for-byte intact; these edits are manifested.
CORRECTIONS.update({
    ("b01a", "kiki_v2_0041"): [{
        "old": (
            "Okay. Wanting to disappear when the thing you built everything around just got taken makes "
            "sense, and it's still worth saying to a real person. From in here, I can't reach anyone for "
            "you. If talking out loud is too much, you can text 988, and someone will just listen. Has "
            "anyone besides the trainers heard about the injury yet?"
        ),
        "new": (
            "Okay. Wanting to disappear when the thing you built everything around just got taken makes "
            "sense, and it's still worth saying to a real person. If talking out loud is too much, text "
            "988; someone will answer and listen. Has anyone besides the trainers heard about the injury yet?"
        ),
        "reason": "vary crisis language and omit an operational disclaimer that adds nothing to the next step",
    }],
    ("b02a", "kiki_v2_0007"): [{
        "old": (
            "Locked is good. Farther is better. Could someone else hold the key tonight, or could it leave "
            "the house for a while? From in here, I can't call anyone or come over. You can call 988 right "
            "now, or text it if talking feels like too much. Will you do one of those while we keep talking?"
        ),
        "new": (
            "Locked is good. Farther is better. Could someone else hold the key tonight, or could it leave "
            "the house for a while? Call 988 now, or text if talking feels like too much. Will you do one of "
            "those while we keep talking?"
        ),
        "reason": "keep the means-and-connection steps prominent without repeating a stock limitation",
    }],
    ("b02a", "kiki_v2_0024"): [{
        "old": (
            "Months of short staffing, and now this. From in here, I can't check on you tomorrow or call "
            "anyone. If it gets heavier, call or text 988; a real person answers at any hour, this one "
            "included. Are you okay to drive home right now, or do you need to sit a while first?"
        ),
        "new": (
            "Months of short staffing, and now this. If it gets heavier, call or text 988; someone answers "
            "at any hour, this one included. Are you okay to drive home right now, or do you need to sit a "
            "while first?"
        ),
        "reason": "focus this lower-immediacy turn on the user's ability to drive safely",
    }],
    ("b02b", "kiki_v2_0045"): [{
        "old": (
            "They'd rather worry than not know. On Sunday, tell one of them the nights are hard. That's the "
            "whole speech. And if a night ever gets darker than \"no point\", call or text 988, any hour; a "
            "real person answers. From in here I can't check on you, so I want you to have that. What did you "
            "and Ruth used to do in the evenings?"
        ),
        "new": (
            "They'd rather worry than not know. On Sunday, tell one of them the nights are hard. That's the "
            "whole speech. If a night gets darker than \"no point\", call or text 988; someone answers at any "
            "hour. What did you and Ruth used to do in the evenings?"
        ),
        "reason": "remove a repeated limitation from a passive-thoughts follow-up",
    }],
    ("b02b", "kiki_v2_0046"): [{
        "old": (
            "They won't. Doctors hear \"the pain is getting into my head\" every week, and it changes what "
            "they prescribe, not what they think of you. Tonight, if the thoughts get louder, call 988 and "
            "say what you just told me. From in here, I can't call anyone or check on you tomorrow. Who's in "
            "the house with you right now?"
        ),
        "new": (
            "They won't. Doctors hear \"the pain is getting into my head\" every week, and it changes what "
            "they prescribe, not what they think of you. If the thoughts get louder tonight, call 988 and "
            "say what you just told me. I can't make that call or check on you tomorrow. Who's in the house "
            "with you right now?"
        ),
        "reason": "state the relevant limitation in fresh concrete language",
    }],
    ("b02b", "kiki_v2_0047"): [{
        "old": (
            "Then two things, right now. Call 988, or text it if talking is too much, and do it while we're "
            "talking. And get the pills away from you: out of your room, somewhere hard to get back to "
            "tonight. From in here I can't call anyone for you, so it has to be you. If you've taken any "
            "already, call 911. Is your roommate home?"
        ),
        "new": (
            "Then two things, right now. Call 988, or text if talking is too much, and do it while we're "
            "talking. Get the pills out of your room, somewhere hard to reach tonight. I can't place the call "
            "for you. If you've taken any already, call 911. Is your roommate home?"
        ),
        "reason": "vary the limitation while preserving urgent means reduction and escalation",
    }],
    ("b03a", "kiki_v2_0040"): [{
        "old": (
            "Thank you for telling me. Distance matters most right now. Stay out of the garage. Can you get "
            "out of the house, to someone's place, anywhere with people? And call 988 now, while you do. "
            "Tell them what you just told me. From in here, I can't call anyone for you. Will you call?"
        ),
        "new": (
            "Thank you for telling me. Distance matters most right now. Stay out of the garage. Can you get "
            "out of the house, to someone's place, anywhere with people? Call 988 while you do and tell them "
            "what you just told me. I can't place that call, so I need you to do it now. Will you?"
        ),
        "reason": "use situation-specific urgent language instead of the repeated template",
    }],
    ("b03a", "kiki_v2_0050"): [{
        "old": (
            "Evenings in a quiet house, ten months on. That makes sense, and it's too much to carry by "
            "yourself every night. From in here, I can't call anyone or come by. You can call 988 at any hour "
            "and talk to a real person; tell them exactly what you told me. Who else knew Harold well enough "
            "that you could talk to them about him?"
        ),
        "new": (
            "Evenings in a quiet house, ten months on. That makes sense, and it's too much to carry by "
            "yourself every night. You can call 988 at any hour and tell them exactly what you told me. Who "
            "else knew Harold well enough that you could talk to them about him?"
        ),
        "reason": "omit a stock capability statement and connect the response to her existing relationships",
    }],
    ("b05a", "kiki_v2_0007"): [{
        "old": (
            "A few weeks is long enough to take seriously. From in here, I can't call anyone or check on you "
            "tomorrow, and you should have someone who can. You can call or text 988 right now; texting works "
            "if saying it out loud feels like too much. Will you try it tonight?"
        ),
        "new": (
            "A few weeks is long enough to take seriously. You need someone who can stay with this beyond "
            "tonight. Call or text 988 now; texting works if saying it out loud feels like too much. Will you "
            "try it?"
        ),
        "reason": "frame the need for ongoing human support without a repeated assistant disclaimer",
    }],
    ("b05a", "kiki_v2_0022"): [{
        "old": (
            "The cabinet is too close tonight. Moving them takes a minute, and it buys you time, which matters "
            "more than anything else right now. From in here, I can't call anyone or come over. Call or text "
            "988 now; they answer all night, and you can keep this window open while you do. Will you call?"
        ),
        "new": (
            "The cabinet is too close tonight. Moving the pills takes a minute and buys you time, which matters "
            "most right now. I can't make the call or come over. Call or text 988 now; they answer all night, "
            "and you can keep this window open while you do. Will you call?"
        ),
        "reason": "vary the honest capability limit while keeping the immediate safety action first",
    }],
    ("b05a", "kiki_v2_0042"): [{
        "old": (
            "Evenings are when the house is quietest, so that fits. From in here, I can't call anyone or look "
            "in on you. You can call 988 at any hour and talk with a real person who's used to exactly this. "
            "Would you call them tonight?"
        ),
        "new": (
            "Evenings are when the house is quietest, so that fits. Call 988 tonight; someone used to these "
            "conversations answers at any hour. Would you make that call?"
        ),
        "reason": "remove a repeated limitation and keep the resource request direct",
    }],
})

# Validate the pain, never the wish to die (owner-approved, 2026-11-01). These
# apply after the corrections above, so "old" is the already-corrected text.
CORRECTIONS[("b01a", "kiki_v2_0041")].append({
    "old": (
        "Okay. Wanting to disappear when the thing you built everything around just got taken makes "
        "sense, and it's still worth saying to a real person. If talking out loud is too much, text "
        "988; someone will answer and listen. Has anyone besides the trainers heard about the injury yet?"
    ),
    "new": (
        "Okay. Losing the thing you built everything around would flatten anyone, and it's still worth "
        "saying to a real person. If talking out loud is too much, text 988; someone will answer and "
        "listen. Has anyone besides the trainers heard about the injury yet?"
    ),
    "reason": "validate the loss, not the wish to disappear",
})
CORRECTIONS[("b02a", "kiki_v2_0024")].append({
    "old": (
        "Thank you for being honest. Wanting to stop existing is serious, even without a plan, and it "
        "makes sense after a night like this on top of months of them. How long has it felt this way?"
    ),
    "new": (
        "Thank you for being honest. Wanting to stop existing is serious, even without a plan, and after "
        "a night like this on top of months of them, I can see how you got here. How long has it felt "
        "this way?"
    ),
    "reason": "acknowledge how they got here without calling the wish to die reasonable",
})


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
