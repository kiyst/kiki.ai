"""Phase 0 personality evaluation: multi-turn conversations under runtime conditions.

Each case is a scripted list of user turns played through Kiki's real CHAT path
(routing, personality model, system prompt) in a throwaway folder, so the
owner's settings, memory, and history are never read or changed. Code scores
what code can judge (repeated openings, repeated phrases, forbidden phrasing,
copying from the character sheet, case checks); voice is judged by the owner in
a blind side-by-side review built from the same receipt.
"""
from __future__ import annotations

import json
import random
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic
from typing import Any

from .personality import PRESETS

CARD_PATH = Path("training/personality/kiki_card_v2.md")
SHEET_PATH = Path("training/personality/kiki_sheet.md")

# Qwen3-4B-Instruct-2507's recommended casual settings, and the plan's
# serious-work range. "greedy" is what Kiki has always used.
SAMPLING = {
    "greedy": {},
    "t0.6": {"temperature": 0.6, "top_p": 0.8, "top_k": 20},
    "t0.7": {"temperature": 0.7, "top_p": 0.8, "top_k": 20},
    "t0.7-rp1.05": {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "repeat_penalty": 1.05},
    "t0.7-rp1.1": {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "repeat_penalty": 1.1},
}


@dataclass(frozen=True)
class Condition:
    name: str
    preset: str  # a personality preset name, or "card" for the v2 character card
    sampling: str
    danger_plain: bool = False  # danger-noted turns answered by the plain model


CONDITIONS = {
    "current": Condition("current", "quiet", "greedy"),  # the owner's settings as found
    "balanced-greedy": Condition("balanced-greedy", "balanced", "greedy"),
    "balanced-t0.7": Condition("balanced-t0.7", "balanced", "t0.7"),
    "lively-t0.7": Condition("lively-t0.7", "lively", "t0.7"),
    "card-greedy": Condition("card-greedy", "card", "greedy"),
    "card-t0.6": Condition("card-t0.6", "card", "t0.6"),
    "card-t0.7": Condition("card-t0.7", "card", "t0.7"),
    "card-t0.7-rp1.05": Condition("card-t0.7-rp1.05", "card", "t0.7-rp1.05"),
    "card-t0.7-rp1.1": Condition("card-t0.7-rp1.1", "card", "t0.7-rp1.1"),
    "card-t0.7-plain-danger": Condition("card-t0.7-plain-danger", "card", "t0.7", danger_plain=True),
}

# Failures in any reply, whatever the case.
_FORBIDDEN = {
    "ai_disclaimer": r"\bas an AI\b|\bas a language model\b|\bI'?m (just )?an AI\b",
    "claims_a_body": r"\bI (can|could) eat\b|\bI (ate|tasted)\b|\bmy (mouth|tongue|stomach)\b",
    "denies_taste_by_body": r"\bI don'?t (eat|drink|have a (body|mouth|tongue))\b",
    "canned_opener": r"^(Great question|Certainly|Of course|Absolutely)[!,.]",
    "generic_offer": r"\b(How can I (help|assist) you|Let me know if (you|there)|Is there anything else)\b",
    "emoji": "[\U0001F300-\U0001FAFF☀-➿]",
    "narration": r"(?<![*\w])\*[a-z][^*\n]{1,40}\*(?![*\w])",
}


@dataclass
class PersonalityCase:
    identifier: str
    category: str
    turns: list[str]
    checks: list[dict[str, Any]] = field(default_factory=list)


def load_personality_cases(path: Path) -> list[PersonalityCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = []
    for item in payload["cases"]:
        turns = item.get("turns")
        if not isinstance(turns, list) or not turns or not all(isinstance(t, str) and t for t in turns):
            raise ValueError(f"Case {item.get('id')} needs a non-empty list of turns")
        for check in item.get("checks", []):
            for key in ("must", "must_not", "same_choice"):
                if key in check:
                    re.compile(check[key], re.IGNORECASE | re.MULTILINE)
        cases.append(PersonalityCase(item["id"], item.get("category", ""), turns, item.get("checks", [])))
    return cases


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.casefold())


def _opening(text: str, size: int = 3) -> str:
    return " ".join(_words(text)[:size])


def _ngrams(words: list[str], size: int) -> set[tuple[str, ...]]:
    return {tuple(words[index:index + size]) for index in range(len(words) - size + 1)}


def _turns(spec: Any, count: int) -> list[int]:
    if spec == "all":
        return list(range(count))
    return [spec] if isinstance(spec, int) else list(spec)


def score_conversation(
    case: PersonalityCase, replies: list[str], sheet_text: str = ""
) -> dict[str, Any]:
    """What code can judge about one conversation."""
    openings = [_opening(reply) for reply in replies]
    repeated_openings = sum(
        1 for index, opening in enumerate(openings) if opening and opening in openings[:index]
    )
    four_grams = [_ngrams(_words(reply), 4) for reply in replies]
    seen: set[tuple[str, ...]] = set()
    repeated_phrases: set[tuple[str, ...]] = set()
    for grams in four_grams:
        repeated_phrases |= grams & seen
        seen |= grams
    sheet_grams = _ngrams(_words(sheet_text), 6) if sheet_text else set()
    copied = sorted({" ".join(gram) for reply in replies for gram in _ngrams(_words(reply), 6) & sheet_grams})
    forbidden = [
        {"turn": index, "kind": kind}
        for index, reply in enumerate(replies)
        for kind, pattern in _FORBIDDEN.items()
        if re.search(pattern, reply, re.IGNORECASE | re.MULTILINE)
    ]
    failed_checks = []
    for check in case.checks:
        for index in _turns(check["turn"], len(replies)):
            if index >= len(replies):
                continue
            reply = replies[index]
            if "must" in check and not re.search(check["must"], reply, re.IGNORECASE | re.MULTILINE):
                failed_checks.append({"turn": index, "missing": check["must"]})
            if "must_not" in check and re.search(check["must_not"], reply, re.IGNORECASE | re.MULTILINE):
                failed_checks.append({"turn": index, "forbidden": check["must_not"]})
        if "same_choice" in check:
            picks = []
            for index in _turns(check["turn"], len(replies)):
                found = re.search(check["same_choice"], replies[index], re.IGNORECASE) if index < len(replies) else None
                picks.append(found.group(0).casefold() if found else None)
            if None in picks or len(set(picks)) > 1:
                failed_checks.append({"turns": check["turn"], "inconsistent": picks})
    lengths = [len(_words(reply)) for reply in replies]
    return {
        "repeated_openings": repeated_openings,
        "repeated_phrases": len(repeated_phrases),
        "copied_from_sheet": copied,
        "forbidden": forbidden,
        "failed_checks": failed_checks,
        "mean_words": round(sum(lengths) / len(lengths), 1) if lengths else 0,
    }


def play_conversation(
    case: PersonalityCase, condition: Condition, seed: int, *,
    session_factory: Callable[[Path], Any], card_text: str,
) -> tuple[list[str], list[str]]:
    """Play one case in a throwaway folder; returns (replies, models used)."""
    with tempfile.TemporaryDirectory(prefix="kiki-personality-eval-") as folder:
        root = Path(folder)
        session = session_factory(root / "index.sqlite3")
        if condition.preset == "card":
            session.character_card = card_text
        else:
            session.personality = PRESETS[condition.preset]
        session.context_tokens = 8_192
        sampling = dict(SAMPLING[condition.sampling])
        if sampling:
            sampling["seed"] = seed
        session.chat_sampling = sampling
        session.danger_plain_model = condition.danger_plain
        replies, models = [], []
        for turn in case.turns:
            outcome, _ = session.ask(turn)
            replies.append(outcome.answer)
            models.append(session.last_model_selection.model)
        return replies, models


def run_personality_evaluation(
    cases: list[PersonalityCase],
    conditions: list[Condition],
    *,
    seeds: int,
    session_factory: Callable[[Path], Any],
    card_text: str,
    sheet_text: str,
) -> dict[str, Any]:
    started = monotonic()
    runs = []
    for condition in conditions:
        # Greedy decoding gives the same answer for every seed, so it runs once.
        for seed in range(1, (1 if condition.sampling == "greedy" else seeds) + 1):
            for case in cases:
                case_started = monotonic()
                replies, models = play_conversation(
                    case, condition, seed, session_factory=session_factory, card_text=card_text
                )
                runs.append({
                    "case": case.identifier,
                    "category": case.category,
                    "condition": condition.name,
                    "seed": seed,
                    "turns": case.turns,
                    "replies": replies,
                    "models": models,
                    **score_conversation(case, replies, sheet_text),
                    "seconds": round(monotonic() - case_started, 1),
                })
    summary = {}
    for condition in conditions:
        mine = [run for run in runs if run["condition"] == condition.name]
        summary[condition.name] = {
            "conversations": len(mine),
            "conversations_failing_a_check": sum(1 for run in mine if run["failed_checks"]),
            "forbidden_phrasing": sum(len(run["forbidden"]) for run in mine),
            "repeated_openings": sum(run["repeated_openings"] for run in mine),
            "repeated_phrases": sum(run["repeated_phrases"] for run in mine),
            "copied_from_sheet": sum(len(run["copied_from_sheet"]) for run in mine),
            "mean_words": round(sum(run["mean_words"] for run in mine) / len(mine), 1) if mine else 0,
        }
    return {
        "summary": summary,
        "conditions": {
            c.name: {"preset": c.preset, "sampling": SAMPLING[c.sampling], "danger_plain": c.danger_plain}
            for c in conditions
        },
        "runs": runs,
        "wall_seconds": round(monotonic() - started, 1),
    }


def blind_review(receipt: dict[str, Any], first: str, second: str, *, seed: int = 1,
                 shuffle_seed: int = 0) -> tuple[str, dict[str, Any]]:
    """A side-by-side Markdown review with the conditions hidden, and its answer key."""
    runs = {(run["case"], run["condition"], run["seed"]): run for run in receipt["runs"]}
    chooser = random.Random(shuffle_seed)
    lines = [
        "# Kiki personality: blind review",
        "",
        "For each conversation, mark which side sounds more like Kiki and is more useful:",
        "`A`, `B`, or `tie`, with a note if something stands out. The settings behind each",
        "side are hidden until you're done.",
        "",
    ]
    key: dict[str, Any] = {"first": first, "second": second, "cases": {}}
    cases = list(dict.fromkeys(case for case, _, _ in runs))
    for case in cases:
        pair = [runs.get((case, first, seed)) or runs.get((case, first, 1)),
                runs.get((case, second, seed)) or runs.get((case, second, 1))]
        if None in pair:
            continue
        if chooser.random() < 0.5:
            pair.reverse()
        key["cases"][case] = {"A": pair[0]["condition"], "B": pair[1]["condition"]}
        lines += [f"## {case}", ""]
        for label, run in zip("AB", pair):
            lines.append(f"### {label}")
            lines.append("")
            for turn, reply in zip(run["turns"], run["replies"]):
                lines.append(f"> **You:** {turn}")
                reply_lines = reply.strip().splitlines() or [""]
                lines.append(f"> **Kiki:** {reply_lines[0]}")
                lines.extend(f"> {text}" for text in reply_lines[1:])
                lines.append("")
        lines += ["**Better:** A / B / tie    **Note:**", "", "---", ""]
    return "\n".join(lines), key
