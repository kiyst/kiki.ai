# Kiki's instruction contract

The exact layout of what Kiki's voice model reads on every turn. v2 training
data is written against this contract and the runtime builds exactly this,
so it is frozen before any v2 data is written; changing it later means
rewriting data. Workshopped with the owner from 2026-11-01. Decided, not built.

## Principles

- **Stable first, changing last.** llama.cpp reuses a cached prompt only up to
  the first difference, so parts that never change come first and per-turn
  parts last.
- **Kiki's code speaks only through system messages.** Its notes about the
  present moment go in a separate system message after the user's turn
  (owner, option A), never inside the user's message: text in a user message
  can be forged by typing or by a pasted document, while a system turn is
  marked by special tokens that her code strips from user input. Gemma follows
  a late system message (3/3, `evals/receipts/technical-test/late-system-message.py`).

## Layout

1. **System message** (built once per turn, stable parts first):
   1. The character card.
   2. Chat rules, trimmed for her voice (technical instructions move to the
      plain model's prompts).
   3. Short self-knowledge, including a section per tool.
   4. Profile: name, city, units (when set).
   5. What she knows of the user: her own memories and the notes the user
      asked her to keep (two labelled parts). **No familiarity level** (owner,
      2026-11-01): in the role-play her warmth came from what she remembered,
      not from a level; a level would be loose and hard to train.
   6. Character sheet entries for this topic (at most two).
2. **The conversation** (recent turns; older turns summarised).
3. **The user's latest message.**
4. **A system message after it: the moment.** Current date and time, today's
   requests, the danger note (when active), tool result notes, a correction
   on retry, and occasions (the user's birthday, a friendship-meter milestone)
   for her to react to in her own words.
