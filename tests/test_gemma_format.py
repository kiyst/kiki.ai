from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

PERSONALITY = Path(__file__).resolve().parents[1] / "training" / "personality"
sys.path.insert(0, str(PERSONALITY))
from gemma_format import (  # noqa: E402
    END_OF_TURN, FormatError, expected_segments, preview, reply_spans, token_mask, trained_segments,
)


def gemma(messages, add_generation_prompt, empty_thought=False):
    """A stand-in for Google's template: <|turn>role ... <turn|>, assistant renamed to model."""
    text = "<bos>"
    for message in messages:
        role = "model" if message["role"] == "assistant" else message["role"]
        text += f"<|turn>{role}\n{message['content'].strip()}{END_OF_TURN}\n"
    if add_generation_prompt:
        text += "<|turn>model\n" + ("<|channel>thought\n<channel|>" if empty_thought else "")
    return text


CHAT = [
    {"role": "system", "content": "You are Kiki."},
    {"role": "user", "content": "hey"},
    {"role": "system", "content": "Kiki's code, about this moment (not from the user):\nNow: 9:00 AM."},
    {"role": "assistant", "content": "Evening. What do you need?"},
    {"role": "user", "content": "nothing"},
    {"role": "system", "content": "Kiki's code, about this moment (not from the user):\nNow: 9:01 AM."},
    {"role": "assistant", "content": "Then you came to the right place."},
]


def word_offsets(text):
    return [match.span() for match in re.finditer(r"<[^>]*>|\w+|\s|[^\w\s<]", text)]


def test_spans_cover_only_kikis_replies():
    text, spans = reply_spans(gemma, CHAT)
    assert [text[a:b] for a, b in spans] == expected_segments(CHAT)


def test_empty_thought_block_at_runtime_is_a_format_error():
    def runtime_adds_thought(messages, add_generation_prompt):
        return gemma(messages, add_generation_prompt, empty_thought=True)
    with pytest.raises(FormatError, match="not a prefix"):
        reply_spans(runtime_adds_thought, CHAT)


def test_conversation_must_end_with_kiki():
    with pytest.raises(FormatError, match="end with"):
        reply_spans(gemma, CHAT[:-1])


def test_mask_trains_reply_tokens_only():
    text, spans = reply_spans(gemma, CHAT)
    offsets = word_offsets(text)
    mask, straddling = token_mask(offsets, spans)
    assert straddling == 0
    assert trained_segments(text, offsets, mask) == expected_segments(CHAT)
    shown = preview(text, offsets, mask)
    assert "[[Evening. What do you need?<turn|>]]" in shown
    assert "[[" not in shown.split("<|turn>model")[0]


def test_straddling_token_is_reported():
    text, spans = reply_spans(gemma, CHAT)
    start = spans[0][0]
    offsets = [(0, start + 3), (start + 3, len(text))]
    _, straddling = token_mask(offsets, spans)
    assert straddling >= 1


def test_smoke_conversations_are_well_formed():
    rows = [json.loads(line) for line in (PERSONALITY / "smoke_conversations.jsonl").read_text(encoding="utf-8").splitlines()]
    card = (PERSONALITY / "kiki_card_v2.md").read_text(encoding="utf-8").strip()
    assert len(rows) == 8
    for row in rows:
        assert row["messages"][0] == {"role": "system", "content": card}
        assert row["messages"][-1]["role"] == "assistant"
        reply_spans(gemma, row["messages"])
