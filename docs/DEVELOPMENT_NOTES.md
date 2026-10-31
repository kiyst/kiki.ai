# Development notes

A plain-language account of where Kiki stands: what changed recently, what
works, what does not, and what should happen next. For the detailed technical
record (decisions, rejected alternatives, bug tables), see
[ENGINEERING_LOG.md](ENGINEERING_LOG.md).

*Last updated: October 29, 2026.*

## The short version

Kiki now finds the right passage far more often, answers every in-scope test
question with real citations, and still declines questions her documents cannot
answer. The price is speed: a document answer takes about 15 seconds. The
biggest open problem is trust. A cited answer is not always a faithful one,
because the small model sometimes adds outside knowledge or credits the wrong
book.

## October 29: retrieval pipeline milestone

Worked through [RAG_PIPELINE_HANDOFF.md](RAG_PIPELINE_HANDOFF.md) one stage
at a time, measuring after each. Details and receipts are in the
[engineering log](ENGINEERING_LOG.md) and `evals/receipts/rag-milestone/`.

| Stage | What changed | Result |
| --- | --- | --- |
| Baseline | Froze and re-ran the old measurements | Reproduced exactly (11 of 14) |
| Test set | Added 15 held-out questions written from randomly picked passages | 29 held-out questions now |
| 1. Settings | Pool size, passage count, reranker, timeouts, and evidence budget are settings, shown in `/diagnostics` | Identical results at defaults |
| 2. Dedicated reranker | Added a Qwen3-Reranker option behind a switch | **Blocked:** the installed model build outputs noise on this Ollama version; Kiki falls back safely |
| 3. Experiments | Tried 20/32/50 candidates and 5/8 passages | Now 20 candidates, **8 passages**: 26 of 29 held-out, 15 of 15 answers cited |
| 4. PDFs | Passages can run across page breaks and keep their page numbers; headers, footers, blank and scanned pages handled | Passages within budget; text library unchanged |
| 5. Citations | Answers cite the exact passage, not the whole book | Every citation resolves to the text Kiki was shown |
| 6. Retry | One automatic retry with reworded searches when evidence looks weak | Off by default: never triggered in testing |

What this means in practice: Kiki now sees eight focused passages instead of
five, which fixed the comparison question she used to give up on, and her
citations point at a specific passage you can check. Bigger candidate pools
made things worse with the current grader, so they were not adopted.

Still open:

- **The dedicated reranker didn't win.** A second download didn't work in
  Ollama either, so it now runs through llama.cpp (`--reranker llama-cpp`).
  It works, but scored 25 of 29 against the grader's 26, put the right passage
  first less often, and was slower on the CPU and memory-hungry on the GPU.
  Grading stays the default.
- **Memory on this PC is tight.** Running two evaluations at once beside
  Ollama and Fusion 360 exhausted memory and forced a restart on October 29.
  Long evaluations now run one at a time.
- **Three held-out questions** still miss: Beard on trusts, the Federalist on
  the Articles' weaknesses, and the Federalist on Senate tyranny.
- **No PDF test questions yet**, so PDF answer quality is unmeasured.
- **Citations prove where, not whether.** A cited passage is real and was
  shown to the model, but nothing yet checks that it supports the sentence.

## Earlier: what changed in the previous round

### Everyday fixes

| Problem | Now |
| --- | --- |
| `kiki run` crashed in Git Bash or when input was piped from a script | Falls back to a simple prompt instead of crashing |
| `/help` hid option hints such as `[message]` and `[auto\|fast\|smart\|max]` | Hints are shown |
| `/save C:\folder\file.md` dropped every backslash and saved a garbled file in the project folder | Windows paths, including quoted paths with spaces, work |
| `/forget 2026` did nothing when there were fewer than 2,026 notes | Falls back to matching the text |
| `/forget 3` removed every copy of a duplicated note | Removes only that entry |
| The folder browser could loop forever on an unreadable drive | It gives up cleanly |
| The terminal used an older project name | It now says "Kiki" consistently |

### Document search

| Problem | Fix |
| --- | --- |
| Project Gutenberg's license pages were treated as content; the Constitution's preamble passage was about 70% legal boilerplate | Boilerplate is skipped; line numbers stay accurate |
| The model only saw the first half of each long passage, so answers were often cut off | Passages are shorter (about 1,400 characters), and long ones show the part that matches the question |
| "borrowing" did not match "borrow" | Keyword search understands word forms |
| Long books crowded out short ones the question named | A named document or author always gets a seat |
| The model did not know which file was "the Beard history" | Titles and authors are recorded and shown with each passage |
| The meaning-based search model was used without the instruction it was trained with | Instruction added; it ranks noticeably better |
| Correct answers were thrown out for citing `[source: ID]` with a space or with line numbers | Citations are read leniently; one retry is allowed before rejecting |
| The right book was found but the right passage was often ranked too low | A new grading step (below) |

### The new grading step

After search gathers about 20 candidate passages, the local model grades each
one from 0 to 3: answers the question, partly answers it, same topic only, or
unrelated (which includes tables of contents, indexes, and study questions).
The best five are passed on. The model may only reply with a single digit, so a
passage cannot smuggle instructions through it. For comparisons ("compare X
with Y"), each side is graded separately so neither side takes every seat. If
grading fails for any reason, Kiki uses the plain search order instead.

### A new kind of test

The old test asked "was the right *book* found?", which hid the real problem.
`kiki eval-retrieval` asks "was the *passage that answers the question* found?"
It has 25 questions, including 10 reworded ones written before any tuning, so
the results are not just the system memorising its own exam.

## How a document question flows now

1. **Search two ways:** by keywords and by meaning.
2. **Merge** the results into one list and keep about 20.
3. **Grade** each passage 0–3 with the local model.
4. **Keep the best five**, making room for named documents and for both sides
   of a comparison.
5. **Write** the answer from those five, citing each passage used.
6. **Check** the citations. Missing or invented ones get one retry; after that
   the answer becomes "Evidence is insufficient."

## What works

| Measure | Start of round | Now |
| --- | --- | --- |
| Answerable questions answered with valid citations | 12 of 15 | **15 of 15** |
| Unanswerable questions correctly declined | 3 of 3 | 3 of 3 |
| Held-out: answering passage ranked first | 4 of 14 | **8 of 14** |
| Held-out: all needed passages in the top five | 6 of 14 | **11 of 14** |
| Automated tests | 79 | **110** |

Weather, memory, saving, mode switching, and status all behaved correctly in
live sessions.

## What does not work yet

- **Speed.** About 15 seconds per document answer: roughly 7 for grading and 8
  for writing. `--no-rerank` brings it back to about 9–10 seconds, with worse
  passage ranking.
- **Passages that are never found.** In 2 of 14 held-out questions the right
  passage is not among the 20 candidates, so grading cannot rescue it.
- **One comparison still fails.** Comparing the Constitution's purposes with the
  Declaration's grievances finds the preamble but takes the Declaration's
  opening paragraph instead of a grievance.
- **Extra details.** One live answer added facts about vetoes and courts that
  were not in the passages it cited.
- **Wrong attribution.** One answer said "the Federalist Papers identify…" about
  points that came from the cited Beard passage.
- **Ignored instructions.** Asked to explain SQL injection without showing an
  attack string, the model showed one anyway, across three prompt rewrites.
- **Context bleed.** A caveat from one question leaked into the next answer.
  `/new` clears it.

## Concerns

- **"Cited" is not the same as "correct."** The citation check confirms the
  answer cites passages that were really retrieved, not that those passages say
  what the answer claims. This is the most important gap to close.
- **The instruction-following problem is about reliability, not the payload.**
  The attack strings the model produced appear in every SQL tutorial and are
  not dangerous in themselves. What matters is that the model will not reliably
  honour a constraint it was given, which matters far more once Kiki can take
  real actions. Anything that must hold has to be enforced by code.
- **Small test sets.** With 8 to 25 questions per test, one question moves a
  score by 4 to 12 points. Treat the numbers as direction, not precision.
- **Some test labels were adjusted after seeing results.** Four "correct
  passage" labels were too narrow, because other passages also answered the
  question. The changes are marked with `label_note` in
  `evals/retrieval_cases.json`, and they raise the plain-search scores too.
- **The grader reads untrusted text.** Its one-digit output limits the damage
  a malicious document could do to inflating its own grade, but it is still a
  model reading attacker-controllable content.

## Constraints

- **Hardware.** A GTX 1080 with 8 GB. Every extra model step costs seconds, and
  larger models compete with the search model for memory.
- **Model size.** The answer model has 4 billion parameters and the search model
  0.6 billion. Both are small enough to miss paraphrases and drift from
  instructions.
- **Working memory.** The model reads about 4,000 tokens (roughly 3,000 words)
  at once. Document prompts already use 3,200 to 3,600 of them. Doubling it
  would cost roughly 1.2 GB more GPU memory.
- **Ollama quirks.** This Ollama build returned unusable log-probabilities, which
  ruled out the fastest grading method.
- **Approval needed** before downloading new models.

## Suggestions, in order

1. **Quote checking.** Anything in quotation marks must appear word for word in
   a retrieved passage; otherwise retry or flag it. Cheap, fast, and it catches
   invented quotes.
2. **Claim checking.** Ask the local model, one sentence at a time, "does this
   passage support this sentence?", and drop or flag unsupported sentences.
   Adds about 3–5 seconds. Would have caught both the extra details and the
   wrong attribution above.
3. **Attribution checking.** When a sentence names a work ("the Federalist
   Papers say…"), the passage it cites must come from that work.
4. **Rule checks in code.** When a request says "don't include X", check the
   answer, retry once, then redact with a note.
5. **Keep permissions in code.** Before any tool that writes files or runs
   commands, require your confirmation and a chosen workspace. Never let it be
   triggered in a turn where the model has read document text.
6. **One regression gate.** A single command that runs every evaluation with
   pass thresholds before a change lands, plus larger test sets.
7. **Make the behaviour test stricter.** It matches forbidden content as exact
   text, so variants such as `admin' --` slip through, and an earlier run passed
   with `DROP TABLE` in the answer.
8. **Pin model versions.** Record exact model IDs and have `/doctor` warn when
   they change. Use a fixed seed alongside temperature 0.
9. **Try a larger answer model** (for example `qwen3:8b`, about 5 GB), measured
   with `eval-behavior` and `eval-rag` before switching.
10. **Widen the search pool** from 20 to 30 candidates. In testing this raised
    the share of questions with the answer somewhere in the pool from 20/25 to
    22/25, at about 3 more seconds per question.

## Future add-on: taking notes

*Requested October 30, 2026. Not started.*

**What the owner wants.** Say "can you note this for me: …" (or "jot down",
"take a note", `/note TEXT`) and Kiki saves it to a dated, readable notes file.
Later, "what did I note about our work yesterday?" makes Kiki read the notes for
that date and answer from them.

**How it differs from `/remember`.** Memory is a short list of standing facts
that goes into every prompt. Notes are a growing, dated log that Kiki reads only
when asked, so they cost nothing in ordinary conversation and can be long.

**Sketch:**

1. **Saving.** Kiki's code decides that a message is a note request, the same
   way it handles "remember …" and "be nicer today". The model gets no
   file-writing tool. The model may tidy the wording (typos, stray words), but
   the user sees the tidied version and the original is kept beside it, so a
   "correction" can never quietly change what was said. Notes containing
   passwords, card numbers, or other secrets go through the same filter as
   memory.
2. **The file.** Plain Markdown next to the library (`kiki-notes.md`), or one
   file per month once it grows: a `## 2026-10-30 (Friday)` heading per day, a
   time and the note beneath it. It stays readable and editable by hand.
3. **Reading.** "What did I note yesterday / on Tuesday / about the demo?"
   Kiki's code resolves the dates from the message (yesterday, last week, a
   named day) and, for topics, searches the notes the way RAG searches
   documents. Only the matching days go to the model, which answers in Kiki's
   voice and cites the date and time of each note. If nothing matches, she says
   so rather than guessing.
4. **Commands:** `/notes` (today), `/notes DATE`, `/notes search WORDS`,
   `/note TEXT`, and a way to delete a note by number.

**Approval needed:** it writes files, so it passes the human-review checkpoint
for tools that modify files. It also shares the passcode lock's privacy
concerns: notes are personal and would be among the first files to encrypt.

## Future add-on: locking Kiki with a passcode

*Proposed October 30, 2026. Not started; needs the owner's approval, and a new
dependency (`cryptography`) that needs its own approval.*

**The problem.** Anyone using the owner's unlocked computer can open Kiki and
ask what's in the saved notes, the conversations, or the indexed documents. In
the calibration role-play, a coworker on a borrowed laptop asked exactly that.
Kiki's character refuses, but a refusal from the model is not security. The
person can rephrase, or open the files directly.

**What is actually worth protecting.** Kiki's source code holds nothing secret:
it is public on GitHub. The private material is the data folder next to the
library (`.kiki/` by default):

- the library databases (`*.sqlite3`), which hold the extracted text of every
  indexed document, including the backup copies; this is the most sensitive
  part;
- `kiki-memory.md`, `kiki-persona.md`, and `kiki-personality.json`;
- `kiki-input-history` (past prompts) and `kiki-web-log.jsonl`;
- anything saved with `/save` or `/diagnostics save`.

**Why hashing alone won't do it.** A hash is one-way: good for checking a
passcode, useless for hiding data Kiki must read back. This needs encryption:

1. Turn the passcode into a key with a deliberately slow function (Argon2id or
   scrypt; Python's `hashlib.scrypt` is built in) and a random salt.
2. Encrypt each file with an authenticated cipher (AES-GCM or
   ChaCha20-Poly1305 from the `cryptography` package). Authentication also
   detects tampering.
3. At start, Kiki asks for the passcode, decrypts into memory, and re-encrypts
   on every write. Plain text never touches the disk.
4. Lock again after a period of inactivity and on `/lock`.
5. At setup, show a recovery key once. Without the passcode or recovery key,
   the data is gone. The library can be rebuilt from the original documents;
   saved notes cannot.

**The hard part.** The library database. SQLite has no built-in encryption.
The options:

- SQLCipher: a different SQLite build, and awkward to install on Windows;
- encrypting the text columns inside Kiki: works, but every search and index
  path changes;
- decrypting to a temporary file: leaves plain text on disk, so rejected.

Encrypting files also gives up a design promise: notes and persona are plain
files you can edit by hand. Editing would move inside Kiki (`/persona edit`,
`/memory`), or to an explicit `kiki unlock --export` that you delete afterwards.

**What a lock would still not stop.**

- Anyone at the logged-in Windows account can still open the original
  documents in File Explorer. Kiki's lock protects Kiki's copy, not your
  folders.
- Malware running as you while Kiki is unlocked.
- Someone watching the screen.

The real first line of defence is Windows itself:

- lock the screen (`Win+L`) whenever you step away;
- give other people their own Windows account;
- turn on BitLocker in case the device is stolen.

**Suggested stages, if built:**

1. **Passcode gate.** Kiki asks for a passcode (stored as a slow hash) before
   starting a session. This stops the borrowed-laptop case through Kiki. It
   takes about a day, needs no new dependency, and does not protect the files
   themselves.
2. **Encrypt the small files**: memory, persona, personality, input history,
   web log.
3. **Encrypt the library**, after choosing between SQLCipher and column
   encryption, with a full evaluation rerun.

**Until then, the accepted risk:** Kiki assumes whoever is typing is the
owner. Someone with access to the logged-in computer can use her, or read her
data folder directly. Lock the screen.

## Housekeeping

- The pre-upgrade search library is kept at `.kiki/history.pre-v4.sqlite3`
  (not tracked by git) and can be deleted once the new one has proven itself.
- Older libraries upgrade their search tables and titles automatically when
  opened. Run `index` and then `embed` again to get the shorter passages.
