# Kiki's tools: how they behave

Detailed behaviour of the tools in `KIKI_PRODUCT_MAP.md` ("Tools after v2"),
decided with the owner from 2026-11-01 so that tool conversations can be
role-played and written as training data. Decided, not built (decide, then
build). Each decision is the owner's unless marked as a proposal.

## Who handles a tool turn

1. **Choosing the tool and its arguments:** the plain model (adapter off).
   When intent or an argument is ambiguous, she asks instead of guessing.
2. **Confirmation** (manual actions): in the chat box, a plain summary
   ("Move 312 files into 6 folders"), Allow / Deny, and the full details one
   click away. File changes are always manual.
3. **Running it:** Kiki's code, which keeps the undo log.
4. **The result note:** a short note from her code, seen only by the model:
   what happened, what was skipped and why, whether undo is available.
5. **The reply:** for everyday tools (notes, timer, to-do, file management,
   opening files) her **voice** writes it from the note; for technical results
   (code, documents, web) the plain model writes it, dry.

Consequence for training: v2 voice data never contains tool-call formats,
only result notes and her replies to them. Rules from the role-play apply: she
reports what happened and stops; no unsolicited offers.

## Folder access

File tools work only inside folders listed in Settings → Folders; system
folders stay blocked. Asked about a folder she wasn't given, her code shows a
one-click prompt in the chat box: "Give Kiki access to Downloads?" with
**Allow once / Always / Deny**. She continues if allowed.

## When the user denies

One short line in her voice, then she drops it ("Fine. It stays a
disaster."). No asking why, no retry, no alternatives.

## Undo

"Undo that", `/undo`, or an **Undo** button on the result line reverses the
most recent action (or one chosen from the log), with its own confirmation
showing what will be restored. Files changed since are skipped and named in
the note. Undo stays available for **7 days**; the log (old and new paths)
lives outside the model.

## Name clashes

Renamed the way Windows does (`invoice (2).pdf`); nothing is overwritten.
The note lists renamed files so she can mention them. Overwriting is a
manual-only action of its own.

## Sorting by type

Her code holds a fixed map from file extension to folder: Images, Documents,
PDFs, Spreadsheets, Installers, Archives, Audio, Video, Code, Other. The
confirmation preview shows the plan with counts ("PDFs: 84 files"). The user
can adjust it in chat before approving ("put PDFs in Documents", "call it
Pictures") and she redoes the plan. The model never judges individual files.

The map covers modern formats too (`.heic`, `.webp`, `.avif` in Images; found
missing in the role-play). Corrections **stick** (Claude's suggestion,
asked for by the owner): "`.heic` goes in Images" or "put PDFs in Documents" is saved by her
code as a sort preference, visible and editable in Settings, used for every
later sort, and limited to sorting. She mentions it once ("`.heic` goes to
Images from now on"), which is allowed only because the save is real. Gaps in
the map are fixed in code for everyone; tastes become the user's preferences.

## Views are not actions

Showing a folder or file list in her file-browser window ("what's in
Other?") needs no confirmation: it reads, it changes nothing, and it opens no
other app. While a confirmation is open she says nothing and waits.

## Timer

A small separate program (see the product map for the alert). It takes both
countdowns ("in 20 minutes") and clock times ("at 6 pm", "Friday at 9"), so
"remind me to call mom at 6" becomes a timer labelled "Call mom". It runs even
when Kiki is closed or asleep. If the PC is off or asleep at that time, the
timer fires on wake, marked late; she says this once, the first time someone
sets a timer.

Training consequence: once the timer ships, "I can't set reminders" (round 1
role-play, smoke samples) is wrong. v2 data matches what she can do when v2
ships; per the no-unbuilt-tools rule, timer conversations are written when the
timer is built.

Several named timers at once; "what timers do I have?" lists them and "cancel
the pasta one" cancels by name. **Repeats:** daily, weekdays, or weekly on a
given day, chosen from that fixed list (the plain model fills a time and a
repeat choice; no free-form date patterns). The confirmation shows what was
understood and the next time ("Stand-up: every weekday at 9:00 AM. Next:
Tuesday."). A repeat missed while the PC was off fires once on wake, marked
late. Skipping one occurrence isn't supported; cancelling stops the series.
Other patterns get an honest "I can only repeat daily, on weekdays, or
weekly".

## Already specified elsewhere

- **Notes:** `DEVELOPMENT_NOTES.md` ("Future add-on: taking notes"): saving,
  the dated file, the secrets filter, answering from notes.
- **To-do list, opening files, summarising a file, clipboard, calculator and
  clock:** `KIKI_PRODUCT_MAP.md` ("Tools after v2").
- **Image reader:** off by default (`model-profiles/gemma4-e4b.md`); when an
  image arrives, her code loads the full model (about 12 s once). Nothing for
  her to say about it.

## Role-play and training

With this spec, tool conversations can be role-played: the scene note gives
the result note her code would leave, and the owner answers as Kiki. Training
data for a tool is written when that tool is built, so it matches what she can
actually do.

## Her self-knowledge of each tool

`self_knowledge.py` gets a section per tool: what it does, what it can't do,
what the sort map covers, and what happens on clashes, undo, and denial, so
"can you sort by project?" gets an accurate answer instead of an improvised
one, and reviewers can check her claims against it (owner, after the
role-play's `.heic` gap).

## Games (owner, 2026-11-01)

Her code holds everything hidden or random; the moment note carries the
state each turn (about 20-40 tokens: "Game: 20 questions. Your pick: a
lighthouse. Questions so far: 2 of 20."); her voice plays in character.
Started like any tool (plain language or `/game`); ends on a win or loss,
when the user stops, or when the conversation moves on. Stage 7.

- **20 questions:** she picks (at random from a bundled list, so the model's
  bias doesn't choose) or guesses the user's pick.
- **Rock paper scissors:** her move is fixed by code before the user types
  theirs.
- **Hangman:** the word is held by code, and **code draws the gallows** as
  text art in the chat as wrong guesses come in (models garble text art).
- **Coin flip** (and dice): code randomness.
- **Connect 4,** in its own window, if it fits: code plays (a small search is
  enough), she comments.
- **Chess,** in its own window, if it fits: a chess engine plays, never the
  model (small models play illegal moves); she comments. Library choice is a
  review checkpoint: the common Python chess library and Stockfish are GPL,
  which needs checking against Kiki's licence (the repo has none yet).
- Left out: would-you-rather (too loose); trivia (owner unsure how it would
  work; it would need a bundled question set with answers).
