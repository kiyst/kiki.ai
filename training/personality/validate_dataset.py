from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path


DATASET = Path(__file__).with_name("kiki_personality_v1.review.jsonl")
ALLOWED_ROLES = {"system", "user", "assistant"}
ALLOWED_PROVENANCE = {"human_seed_cleaned", "synthetic_curated"}
PLACEHOLDERS = (
    "*explains",
    "*usual tool",
    "todo",
    "tbd",
    "insert answer",
    "lorem ipsum",
)
GENERIC_OPENERS = (
    "how can i help you today",
    "as an ai language model",
    "i'm here to assist",
    "i am here to assist",
    "i'd be happy to help",
    "i would be happy to help",
)
SIGNATURES = (
    "womp womp",
    "schrödinger",
    "terminator",
    "lobotomy successful",
    "go outside",
)


def normalized(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def fail(errors: list[str], line_number: int, message: str) -> None:
    errors.append(f"line {line_number}: {message}")


def main() -> int:
    errors: list[str] = []
    ids: set[str] = set()
    exact_conversations: set[str] = set()
    normalized_prompts: dict[str, str] = {}
    categories: Counter[str] = Counter()
    provenance: Counter[str] = Counter()
    signatures: Counter[str] = Counter()
    records = 0

    for line_number, raw in enumerate(DATASET.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        records += 1
        try:
            record = json.loads(raw)
        except json.JSONDecodeError as exc:
            fail(errors, line_number, f"invalid JSON: {exc}")
            continue

        identifier = record.get("id")
        if not isinstance(identifier, str) or not re.fullmatch(r"kiki_sft_\d{4}", identifier):
            fail(errors, line_number, "id must match kiki_sft_NNNN")
        elif identifier in ids:
            fail(errors, line_number, f"duplicate id {identifier}")
        else:
            ids.add(identifier)

        category = record.get("category")
        if not isinstance(category, str) or not category:
            fail(errors, line_number, "missing category")
        else:
            categories[category] += 1

        source = record.get("provenance")
        if source not in ALLOWED_PROVENANCE:
            fail(errors, line_number, f"invalid provenance {source!r}")
        else:
            provenance[source] += 1

        messages = record.get("messages")
        if not isinstance(messages, list) or len(messages) < 2:
            fail(errors, line_number, "messages must contain at least user and assistant")
            continue
        if messages[-1].get("role") != "assistant":
            fail(errors, line_number, "conversation must end with an assistant response")

        previous_role = None
        for index, message in enumerate(messages):
            if not isinstance(message, dict):
                fail(errors, line_number, f"message {index} is not an object")
                continue
            role = message.get("role")
            content = message.get("content")
            if role not in ALLOWED_ROLES:
                fail(errors, line_number, f"message {index} has invalid role {role!r}")
            if not isinstance(content, str) or not content.strip():
                fail(errors, line_number, f"message {index} has empty content")
                continue
            if role == "system" and index != 0:
                fail(errors, line_number, "system messages may appear only first")
            if role == previous_role and role != "system":
                fail(errors, line_number, f"consecutive {role} messages")
            previous_role = role
            lowered = content.casefold()
            for placeholder in PLACEHOLDERS:
                if placeholder in lowered:
                    fail(errors, line_number, f"placeholder text {placeholder!r}")
            if role == "assistant":
                for opener in GENERIC_OPENERS:
                    if opener in lowered:
                        fail(errors, line_number, f"generic assistant phrase {opener!r}")
                for signature in SIGNATURES:
                    if signature in lowered:
                        signatures[signature] += 1

        canonical = json.dumps(messages, sort_keys=True, ensure_ascii=False)
        if canonical in exact_conversations:
            fail(errors, line_number, "exact duplicate conversation")
        exact_conversations.add(canonical)

        first_user = next((m["content"] for m in messages if m.get("role") == "user"), "")
        prompt_key = normalized(first_user)
        if prompt_key in normalized_prompts:
            fail(errors, line_number, f"normalized prompt duplicates {normalized_prompts[prompt_key]}")
        else:
            normalized_prompts[prompt_key] = identifier

    for phrase, count in signatures.items():
        if count > 2:
            errors.append(f"signature phrase {phrase!r} appears {count} times; maximum is 2")

    print(f"records: {records}")
    print("categories:")
    for name, count in sorted(categories.items()):
        print(f"  {name}: {count}")
    print("provenance:")
    for name, count in sorted(provenance.items()):
        print(f"  {name}: {count}")

    if errors:
        print("errors:")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("validation: passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
