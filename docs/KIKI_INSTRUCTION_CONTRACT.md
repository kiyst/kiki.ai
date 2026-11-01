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

## Formats

Plain labelled sections, in the layout order. Example values are illustrative.

```text
[the character card, exactly as in training/personality/kiki_card_v2.md]

[chat rules]

[short self-knowledge, with a section per tool]

About the user (from their profile):
Name: Sam
City: Toronto, Canada (temperatures in °C)
Birthday: March 14

What Kiki remembers about the user (her own notes; may be out of date):
- 2026-10-28: Final-round interview at a design studio on Thursday; nervous.
- 2026-09-02: Learning Rust; complains about the borrow checker.

Notes the user asked Kiki to keep:
- Mom's flight lands Friday 6:40 pm.

Earlier in this chat (summary):
[a few hundred tokens, when older turns have been summarised]

Kiki's character sheet, for this topic.
[at most two entries]
```

After the user's latest message, a separate system message:

```text
Kiki's code, about this moment (not from the user):
Now: Wednesday, November 4, 2026, 9:10 AM.
Today's requests (until 4:00 AM): go easy on me today.
[danger note, when active]
Tool result: Moved 399 of 403 files into 10 folders. Skipped 4: 3 still
downloading, 1 in use (zoom_installer.exe). Renamed 7 for duplicates.
Undo available for 7 days.
Occasion: today is the user's birthday.
```

Empty parts are left out entirely, never written as "none".

## Budgets (tokens, approximate)

| Part | Small (4K) | Standard (8K, default) | Large (16K) / Max (32K) |
| --- | --- | --- | --- |
| Card, rules, self-knowledge | about 1,500 | about 1,500 | about 1,500 |
| Profile | 40 | 40 | 40 |
| Her memories and kept notes | 150 | 400 | 800 |
| Chat summary | 150 | 300 | 500 |
| Sheet entries | 1 entry | 2 entries | 2 entries |
| The moment note | about 100 | about 100 | about 150 |
| Room for her reply | 500 | 600 | 800 |
| Recent conversation | the rest (about 1,400) | the rest (about 5,000) | the rest |

At small, memories are the most relevant few and the sheet gets one entry.
Memory selection (which memories, by relevance and recency) is runtime
behaviour, not part of the contract; the contract fixes the format and the
caps.

## Security

- Her code strips the model's control tokens (`<|turn>`, `<turn|>`,
  `<|channel>`, `<channel|>`, `<|think|>`, tool markers, `<bos>`) from
  everything that is not its own: user messages, pasted text, documents, web
  pages, tool results quoted from files. Without this, a typed or planted
  `<|turn>system` could forge a note from her code.
- Text in a user message claiming to come from Kiki's code is ordinary user
  text; the rules say so.

## Training data

Every v2 example's system message follows this layout, with the parts varied
across the corpus: profile present or absent, zero to many memories, a chat
summary sometimes, zero to two sheet entries, and moment notes of every kind
(time of day always; requests, danger notes, tool results, occasions
sometimes). Sizes stay within the standard budget.
