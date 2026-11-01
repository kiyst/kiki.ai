"""Training format and loss mask for Gemma 4, checked against the runtime format.

The v1 lesson: training text and runtime prompts must be identical. Here the
loss mask is derived from the runtime prompt itself. For each of Kiki's
replies, the prompt the runtime would send (the chat template with
add_generation_prompt=True, thinking off) must be an exact prefix of the
training text, and her reply must follow it directly. Anything in between
(an empty thought block, a stray newline) is a format mismatch and fails the
example. Only her reply text and the end-of-turn marker are trained.

No heavy imports, so the checks run in tests without a GPU.
"""
from __future__ import annotations

from typing import Callable, Sequence

END_OF_TURN = "<turn|>"
Render = Callable[[list[dict], bool], str]


class FormatError(ValueError):
    pass


def reply_spans(render: Render, messages: list[dict]) -> tuple[str, list[tuple[int, int]]]:
    """Training text plus the character spans of Kiki's replies (reply + end marker)."""
    if not messages or messages[-1].get("role") != "assistant":
        raise FormatError("a conversation must end with Kiki's reply")
    full = render(messages, False)
    spans: list[tuple[int, int]] = []
    for index, message in enumerate(messages):
        if message.get("role") != "assistant":
            continue
        turn = sum(1 for m in messages[:index + 1] if m.get("role") == "assistant")
        prompt = render(messages[:index], True)
        if not full.startswith(prompt):
            raise FormatError(f"reply {turn}: the runtime prompt is not a prefix of the training text")
        content = str(message.get("content", "")).strip()
        rest = full[len(prompt):]
        if not content or not rest.startswith(content):
            raise FormatError(f"reply {turn}: text between the prompt and the reply: {rest[:40]!r}")
        end = len(prompt) + len(content)
        if not full.startswith(END_OF_TURN, end):
            raise FormatError(f"reply {turn}: the reply is not followed by {END_OF_TURN}")
        spans.append((len(prompt), end + len(END_OF_TURN)))
    return full, spans


def token_mask(offsets: Sequence[tuple[int, int]], spans: list[tuple[int, int]]) -> tuple[list[bool], int]:
    """Which tokens are trained, and how many tokens straddle a span edge."""
    mask, straddling = [], 0
    for start, end in offsets:
        inside = any(start < span_end and end > span_start for span_start, span_end in spans)
        if inside and any(start < edge < end for span in spans for edge in span):
            straddling += 1
        mask.append(inside)
    return mask, straddling


def trained_segments(text: str, offsets: Sequence[tuple[int, int]], mask: list[bool]) -> list[str]:
    segments, current = [], []
    for (start, end), trained in zip(offsets, mask):
        if trained:
            current.append(text[start:end])
        elif current:
            segments.append("".join(current))
            current = []
    if current:
        segments.append("".join(current))
    return segments


def expected_segments(messages: list[dict]) -> list[str]:
    return [str(m["content"]).strip() + END_OF_TURN for m in messages if m.get("role") == "assistant"]


def preview(text: str, offsets: Sequence[tuple[int, int]], mask: list[bool]) -> str:
    """The training text with trained parts wrapped in [[ ]], for a human to read."""
    out, inside, cursor = [], False, 0
    for (start, end), trained in zip(offsets, mask):
        out.append(text[cursor:start])
        if trained and not inside:
            out.append("[[")
        elif not trained and inside:
            out.append("]]")
        inside = trained
        out.append(text[start:end])
        cursor = end
    if inside:
        out.append("]]")
    out.append(text[cursor:])
    return "".join(out)
