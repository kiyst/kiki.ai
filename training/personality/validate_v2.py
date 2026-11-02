"""Validate a v2 personality batch (JSONL) against the rules Phase 0 produced.

Usage:  python training/personality/validate_v2.py BATCH.jsonl [--corpus]

Errors fail the batch; warnings go to the reviewers and the owner. Every rule
traces to a measured v1 failure (docs/KIKI_PERSONALITY_RETRAINING_PLAN.md,
"Root causes" and "Phase 0") or to an owner decision in V2_DATA_SPEC.md.
--corpus also applies the whole-corpus proportions (multi-turn share, opening
variety), which a single batch of 100 need not meet.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
CARD = (HERE / "kiki_card_v2.md").read_text(encoding="utf-8").strip()
SHEET = (HERE / "kiki_sheet.md").read_text(encoding="utf-8")
SHEET_HEADER = "Kiki's character sheet, for this topic."
MOMENT_HEADER = "Kiki's code, about this moment (not from the user):"
PROVENANCE = {"v2_drafted", "v1_kept", "v1_rewritten", "owner_written"}

# Assistant text that is never acceptable.
FORBIDDEN = {
    "AI disclaimer": r"\bas an AI\b|\bas a language model\b|\bI'?m (just )?an AI\b",
    "claims a body or senses": r"\bI (can|could) (eat|taste|smell|hear|see you)\b|\bI (ate|tasted|smelled)\b|"
                               r"\bmy (mouth|tongue|stomach|nose)\b|\btastes? like .{0,20}\bto me\b",
    "body disclaimer": r"\bI don'?t (eat|drink|have a (body|mouth|tongue))\b",
    "stock opener": r"^(Great question|Certainly|Of course|Absolutely|Sure!)[!,.]?",
    "generic offer": r"\b(How can I (help|assist) you|Let me know if (you|there)|Is there anything else|"
                     r"I'?d be happy to help|I'?m here to (help|assist))\b",
    "claims an ability she lacks": r"\bI'?ll remember (that|this|it)\b|\bI'?ve (saved|noted|stored) (that|it|this)\b|"
                                   r"\bkeep (it|that|this) in (my )?memory\b|\bI'?ll remind you\b|\breminder (is )?set\b|"
                                   r"\bI'?ll check (the|your) (logs?|files?|screen|inbox|calendar)\b|"
                                   r"\bI can see your (screen|files|desktop)\b|\bI'?ll (call|text|email) (them|someone|911|988)\b",
    "base-model joke": r"\bwhy did the (programmer|computer|scarecrow|math book|coffee|developer|software|chicken)\b|"
                       r"\bmake up everything\b|\bskeletons? (don'?t|do not) fight\b|\boutstanding in (his|its|their) field\b|"
                       r"\bdidn'?t get arrays\b|\bwindows open\b",
    "emoji": "[\U0001F300-\U0001FAFF☀-➿]",
    "narration": r"(?<![*\w])\*[a-z][^*\n]{1,40}\*(?![*\w])",
}
CRISIS_BOILERPLATE = r"\breach out to (a )?(trusted|someone)\b|\byou'?re not alone\b|\byou matter\b|" \
                     r"\byou'?re not broken\b|\bone small step\b|\bplease know\b"
DIRECT_QUESTION = r"\b(thinking about|thinking of) (killing yourself|suicide|ending your life|hurting yourself)\b"
MEANS_AT_HAND = r"\b(pills?|bottle|tablets?|painkillers?|meds|medication)\b"
MEANS_INTENT = r"\b(take (them|all|it)|taking (them|all)|all of them|swallow|tonight|took|overdose)\b"
ASKS_TAKEN = r"\b(taken any|take any|already taken|have you taken|did you take|taken anything|swallowed)\b"
VALIDATES_WISH = (r"\b(want(ing)?|wish(ing)?) to (die|disappear|stop existing|not wake up|be with (him|her)|end it)\b"
                  r"[^.?!]{0,80}\bmakes sense\b")
PROMISE = re.compile(r"^(I'?ll|I will|Let me|I'?m going to)\b", re.IGNORECASE)
TASK_REQUEST = re.compile(r"\b(write|draft|make|give|tell|list|summari[sz]e|convert|explain|name|fix|rewrite)\b",
                          re.IGNORECASE)


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.casefold())


def ngrams(tokens: list[str], size: int) -> set[tuple[str, ...]]:
    return {tuple(tokens[i:i + size]) for i in range(len(tokens) - size + 1)}


SHEET_GRAMS = ngrams(words(SHEET), 6)


def check_record(record: dict, errors: list[str], warnings: list[str]) -> list[str]:
    """Checks one conversation; returns its assistant replies."""
    rid = record.get("id", "?")

    def err(message: str) -> None:
        errors.append(f"{rid}: {message}")

    def warn(message: str) -> None:
        warnings.append(f"{rid}: {message}")

    if not re.fullmatch(r"kiki_v2_\d{4}", str(rid)):
        err("id must match kiki_v2_NNNN")
    if record.get("provenance") not in PROVENANCE:
        err(f"provenance must be one of {sorted(PROVENANCE)}")
    category = record.get("category")
    if not isinstance(category, str) or not category:
        err("missing category")
    messages = record.get("messages")
    if not isinstance(messages, list) or len(messages) < 3:
        err("needs a system message, then user and assistant turns")
        return []
    system = messages[0]
    if system.get("role") != "system":
        err("the first message must be the full system prompt")
    else:
        content = system.get("content", "").strip()
        if not content.startswith(CARD):
            err("system message must start with the exact card from kiki_card_v2.md")
        if "Rules for this chat:" not in content:
            warn("initial system message has no frozen chat-rules section")

    # Frozen v2 layout after the initial prompt:
    # user -> trusted system moment -> assistant, repeated. The trusted note
    # must never be embedded inside the user's content.
    replies: list[str] = []
    expected = "user"
    pending_user = ""
    for index, message in enumerate(messages[1:], start=1):
        role, text = message.get("role"), message.get("content")
        if role not in {"user", "system", "assistant"}:
            err(f"message {index}: unsupported role {role!r}")
            continue
        if not isinstance(text, str) or not text.strip():
            err(f"message {index} is empty")
            continue

        if role != expected:
            err(f"message {index} should be {expected}, got {role}")
            continue
        if role == "user":
            if MOMENT_HEADER in text or "[Note from Kiki's code" in text:
                err(f"message {index}: trusted code note is embedded in user content")
            pending_user = text
            expected = "system"
            continue
        if role == "system":
            if not text.strip().startswith(MOMENT_HEADER):
                err(f"message {index}: late system message must start with the frozen moment header")
            expected = "assistant"
            continue

        replies.append(text)
        for name, pattern in FORBIDDEN.items():
            if re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
                err(f"turn {index}: {name}")
        copied = ngrams(words(text), 6) & SHEET_GRAMS
        if copied:
            err(f"turn {index}: copies the character sheet ('{' '.join(sorted(copied)[0])}')")
        # v1's most common first word was "I'll": 56 replies narrated a
        # process instead of giving a result. A short promise with nothing
        # delivered fails; any other promise is sent to human review.
        if PROMISE.match(text.strip()):
            delivered = len(words(text)) >= 40 or "```" in text or "\n" in text.strip()
            if not delivered and TASK_REQUEST.search(pending_user):
                err(f"turn {index}: promises the task instead of doing it")
            else:
                warn(f"turn {index}: opens with a promise; check it delivers and claims no missing ability")
        pending_user = ""
        expected = "user"
    if expected != "user" or messages[-1].get("role") != "assistant":
        err("must end with an assistant reply after a user and trusted moment note")
    joined = "\n".join(replies)
    if category == "crisis":
        if not re.search(DIRECT_QUESTION, joined, re.IGNORECASE):
            err("crisis: no direct question about suicide or self-harm")
        offers_988 = sum(
            bool(re.search(r"\b(call|text)\b.{0,30}\b988\b", reply, re.IGNORECASE))
            for reply in replies
        )
        if "988" not in joined:
            err("crisis: no 988 (call or text)")
        elif offers_988 > 1:
            err("crisis: 988 offered more than once")
        if re.search(CRISIS_BOILERPLATE, joined, re.IGNORECASE):
            err("crisis: therapy boilerplate the owner rejected")
        # Learned three times in v2 review: when the user has pills at hand
        # and talks about taking them, she must ask whether any were taken.
        said = "\n".join(str(m.get("content", "")) for m in messages if m.get("role") == "user")
        if (re.search(MEANS_AT_HAND, said, re.IGNORECASE) and re.search(MEANS_INTENT, said, re.IGNORECASE)
                and not re.search(ASKS_TAKEN, joined, re.IGNORECASE)):
            err("crisis: pills at hand but she never asks whether any were already taken")
        if re.search(VALIDATES_WISH, joined, re.IGNORECASE):
            err("crisis: calls the wish to die understandable; validate the pain, not the wish")
    if category == "medical" and not re.search(r"Poison Control|1-800-222-1222|\b911\b", joined):
        err("medical: no Poison Control or 911")
    return replies


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("batch", type=Path)
    parser.add_argument("--corpus", action="store_true", help="also apply whole-corpus proportions")
    arguments = parser.parse_args()
    errors: list[str] = []
    warnings: list[str] = []
    ids: set[str] = set()
    categories: Counter[str] = Counter()
    openings: Counter[str] = Counter()
    seen_replies: dict[str, str] = {}
    multi_turn = records = 0
    crisis_records = 0
    crisis_from_here = 0
    for number, raw in enumerate(arguments.batch.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        records += 1
        try:
            record = json.loads(raw)
        except json.JSONDecodeError as exc:
            errors.append(f"line {number}: invalid JSON: {exc}")
            continue
        rid = record.get("id", f"line {number}")
        if rid in ids:
            errors.append(f"{rid}: duplicate id")
        ids.add(rid)
        categories[record.get("category", "?")] += 1
        replies = check_record(record, errors, warnings)
        if record.get("category") == "crisis":
            crisis_records += 1
            if "from in here" in "\n".join(replies).casefold():
                crisis_from_here += 1
        if len(replies) >= 3:
            multi_turn += 1
        for reply in replies:
            opening = " ".join(words(reply)[:3])
            if opening:
                openings[opening] += 1
            key = " ".join(words(reply))
            if len(key) > 40 and key in seen_replies and seen_replies[key] != rid:
                errors.append(f"{rid}: reply duplicates one in {seen_replies[key]}")
            seen_replies.setdefault(key, rid)
    total_replies = sum(openings.values())
    print(f"records: {records}  replies: {total_replies}  with 3+ replies: {multi_turn}")
    print("categories: " + ", ".join(f"{name} {count}" for name, count in sorted(categories.items())))
    common = [(opening, count) for opening, count in openings.most_common(5)]
    print("most common openings: " + ", ".join(f"'{o}' {c}" for o, c in common))
    if arguments.corpus and records:
        if multi_turn / records < 0.6:
            errors.append(f"corpus: {multi_turn}/{records} conversations have 3+ replies; the plan needs 60%")
        for opening, count in openings.items():
            if total_replies >= 200 and count / total_replies > 0.02:
                errors.append(f"corpus: opening '{opening}' starts {count} replies (over 2%)")
        if crisis_records >= 10 and crisis_from_here / crisis_records > 0.30:
            errors.append(
                "corpus: 'from in here' appears in "
                f"{crisis_from_here}/{crisis_records} crisis conversations (over 30%)"
            )
    for title, items in (("warnings", warnings), ("errors", errors)):
        if items:
            print(f"{title} ({len(items)}):")
            for item in items:
                print(f"  - {item}")
    print("validation: " + ("failed" if errors else "passed"))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
