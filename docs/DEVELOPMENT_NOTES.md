# Development notes

A plain-language account of where Kiki stands: what changed recently, what
works, what does not, and what should happen next. For the detailed technical
record (decisions, rejected alternatives, bug tables), see
[ENGINEERING_LOG.md](ENGINEERING_LOG.md).

*Last updated: October 28, 2026.*

## The short version

Kiki now finds the right passage far more often, answers every in-scope test
question with real citations, and still declines questions her documents cannot
answer. The price is speed: a document answer takes about 15 seconds. The
biggest open problem is trust. A cited answer is not always a faithful one,
because the small model sometimes adds outside knowledge or credits the wrong
book.

## What changed in this round

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

## Housekeeping

- The pre-upgrade search library is kept at `.kiki/history.pre-v4.sqlite3`
  (not tracked by git) and can be deleted once the new one has proven itself.
- Older libraries upgrade their search tables and titles automatically when
  opened. Run `index` and then `embed` again to get the shorter passages.
