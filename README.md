# Kiki

*A small, honest assistant that lives on your own machine.*

Kiki is a terminal assistant that runs entirely on local models through
[Ollama](https://ollama.com). She can hold an ordinary conversation, help with
code, check the weather, and, more interestingly, answer questions about your
own documents while showing exactly which passage each answer came from.

She is built around one idea: **it is better to say "the evidence is
insufficient" than to sound confident and be wrong.** Every document answer is
checked against the passages that were actually retrieved, and anything that
cannot be traced back to them is not shown as fact.

```text
RAG you > What does Paine say about hereditary succession?

┌──────────────────────────────── Kiki · RAG ─────────────────────────────────┐
│ Thomas Paine criticizes hereditary succession in Common Sense, arguing that │
│ it opens the door to "the foolish, the wicked, and the improper"… He also   │
│ dismisses the claim that it prevents civil wars, pointing to England's own  │
│ history. [source:c9e633dd29d77ce8]                                          │
└─────────────────────────────────────────────────────────────────────────────┘
                   Verified sources
│ c9e633dd29d77ce8 │ common_sense.txt │ lines 520-532 │
│ c9e633dd29d77ce8 │ common_sense.txt │ lines 555-569 │
```

> **Status:** an actively developed personal prototype. It works well on the
> included history library and is honest about where it does not. See
> [How well it works](#how-well-it-works) and the
> [development notes](docs/DEVELOPMENT_NOTES.md).

## Contents

- [What Kiki can do](#what-kiki-can-do)
- [How a question becomes an answer](#how-a-question-becomes-an-answer)
- [Install](#install)
- [Usage](#usage)
- [Building your own library](#building-your-own-library)
- [Configuration](#configuration)
- [How well it works](#how-well-it-works)
- [Privacy and safety by design](#privacy-and-safety-by-design)
- [Project layout](#project-layout)
- [Development](#development)
- [Roadmap](#roadmap)
- [Acknowledgements](#acknowledgements)
- [License](#license)

## What Kiki can do

- **Talk.** Plain conversation, writing help, and code: explaining, writing,
  reviewing, and debugging. She writes code but never runs it.
- **Answer from your documents.** Point her at a folder of text, Markdown, or
  PDF files. Answers cite the document and line or page they came from.
- **Know when to stop.** Questions the documents cannot answer get "Evidence is
  insufficient" instead of a guess.
- **Check the weather.** Live conditions from Open-Meteo, with a follow-up
  question when a place name is ambiguous ("Springfield… which one?").
- **Remember only what you ask her to.** `/remember` saves a note to a plain
  Markdown file you can read and edit. Secrets, card numbers, and contact
  details are refused.
- **Have a personality you control.** Warmth, wit, opinions, and verbosity are
  adjustable, and her persona lives in an editable text file that never
  overrides the rules about evidence and safety.

Two modes keep these apart. **CHAT** is ordinary conversation with no document
access. **RAG** (retrieval-augmented generation) answers only from your indexed
documents. Each mode keeps its own conversation history.

## How a question becomes an answer

When you ask a document question, Kiki does not just hand it to the language
model. It goes through six steps, each of which can be inspected with `/debug`:

```text
 your question
      │
      ▼
 1. Search two ways ─────── keywords (stemmed: "borrowing" finds "borrow")
      │                     + meaning (local embeddings)
      ▼
 2. Merge into one ranked list of ~20 candidate passages
      │
      ▼
 3. Grade each passage 0–3: "does this actually answer the question?"
      │                     (graded by the local model; one digit only)
      ▼
 4. Keep the best 5 ──────── any document you named gets a seat;
      │                      each side of a comparison gets a seat
      ▼
 5. Write the answer from those 5 passages, citing each one
      │
      ▼
 6. Check the citations ─── invented or missing? one retry, then
                             "Evidence is insufficient"
```

A few details make this work better on a small model:

- Library boilerplate such as Project Gutenberg license pages is ignored.
- Passages are short (about 1,400 characters), so the model reads whole
  passages instead of truncated halves.
- Each file's title and author are recorded, so "the Beard history" or "Paine"
  means something.
- If the grading step fails, Kiki falls back to the merged search order rather
  than failing the question.

## Install

### Requirements

- Windows 10/11 (developed there; other platforms are untested)
- Python 3.12
- [Ollama](https://ollama.com) running locally
- About 3.5 GB of disk for the two default models; a GPU with 6–8 GB is
  comfortable

### Steps

```powershell
git clone https://github.com/kiyst/kiki.ai.git
cd kiki.ai

py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,ollama]"

ollama pull qwen3:4b-instruct
ollama pull qwen3-embedding:0.6b
```

Check that everything is reachable:

```powershell
kiki doctor
```

## Usage

### Start a conversation

```powershell
kiki run
```

You start in **CHAT**. Type `/rag` to ask your documents and `/chat` to switch
back. To use a specific document library:

```powershell
kiki --database .kiki\history.sqlite3 run
```

### Commands inside Kiki

| Command | What it does |
| --- | --- |
| `/chat [message]` | Ordinary conversation |
| `/rag [question]` | Answer from your indexed documents |
| `/sources` | Show the last answer's sources again |
| `/retry` | Ask again for a fresh answer |
| `/copy` | Copy the last answer to the clipboard |
| `/history` | Your last ten prompts in this mode |
| `/save [PATH]` | Save the conversation as Markdown (no path opens a folder browser) |
| `/new` or `/clear` | Start a fresh conversation in this mode |
| `/weather Boston, MA` | Current weather and a short forecast |
| `/database [PATH\|browse]` | Show or switch the document library |
| `/remember TEXT` | Save a note Kiki will keep in mind |
| `/memory` | List saved notes, numbered |
| `/forget NUMBER` | Delete a note by number (or by matching text) |
| `/personality` | Adjust warmth, wit, opinions, and verbosity |
| `/persona [show\|reset]` | View or reset the editable persona file |
| `/model [auto\|fast\|smart\|max]` | Choose a model profile |
| `/status` | Mode, library, models, and settings at a glance |
| `/doctor` | Health check for Ollama, the library, and weather |
| `/debug` | Show search steps and tool calls under each answer |
| `/diagnostics [copy\|save]` | A privacy-filtered report for bug hunting |
| `/capabilities` | What Kiki can and cannot do right now |
| `/help` | All of the above |
| `/quit` | Leave |

### Keyboard

`Enter` sends. `Alt+Enter` or `F2` adds a new line, so pasted multi-line text is
never sent one line at a time. `Tab` completes commands, `↑` recalls earlier
prompts (even after a restart), and `Ctrl+D` exits. Mouse selection belongs to
your terminal, so copying text works the way you expect.

### One-off commands

Every feature also works without opening the chat, and `--json` makes the
output scriptable:

```powershell
kiki chat "Explain mercantilism in plain language."
kiki rag "What does Paine say about hereditary monarchy?" --debug
kiki hybrid-search "Which problems should never get another try?"
kiki weather "Boston, Massachusetts"
kiki --json rag "Why is the judiciary the least dangerous branch?"
```

## Building your own library

Point Kiki at a folder, then create the meaning-based search vectors:

```powershell
kiki --database .kiki\notes.sqlite3 index C:\path\to\your\notes
kiki --database .kiki\notes.sqlite3 embed
kiki --database .kiki\notes.sqlite3 run
```

- Text and Markdown cite line numbers; PDFs cite pages.
- Encrypted, broken, or image-only PDFs are reported and skipped. There is no
  OCR yet.
- Re-running `index` only processes files that changed and removes deleted ones.
- Only folders you index are searchable. Kiki never browses your disk on her own.

**The history library used in testing** is five public-domain works from
Project Gutenberg (the Declaration of Independence, the Constitution, *Common
Sense*, *The Federalist Papers*, and Beard's 1921 *History of the United
States*). The texts are not included in this repository; download them from the
links in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) into
`test-data/history/`, then index that folder.

## Configuration

| Setting | Where | Purpose |
| --- | --- | --- |
| `--database PATH` | command line | Which document library to use (default `.kiki/index.sqlite3`) |
| `--no-rerank` | command line, before the command | Skip the grading step: about 7 s faster, less precise |
| `--model NAME` | command line | Main generation model (default `qwen3:4b-instruct`) |
| `KIKI_MODEL_FAST` / `_SMART` / `_MAX` | environment | Models for each profile; `AUTO` uses FAST for chat and SMART for code and documents |
| `KIKI_FALLBACK_MODEL` | environment | Comma-separated backups if the main model fails |
| `kiki-persona.md` | next to the library | Kiki's editable persona, reloaded on every reply |
| `kiki-memory.md` | next to the library | Your saved notes, plain Markdown |

Document search has its own settings. Each one can be set as an environment
variable or as a command-line flag placed before the command
(`kiki --candidates 32 rag "..."`). The flag wins. The defaults are the setup
measured in the [engineering log](docs/ENGINEERING_LOG.md), and `/diagnostics`
shows the active values.

| Flag | Environment | Default | Purpose |
| --- | --- | --- | --- |
| `--candidates N` | `KIKI_RAG_CANDIDATES` | 20 | Passages gathered before reranking (1–100) |
| `--passages N` | `KIKI_RAG_PASSAGES` | 8 | Passages given to the answer model (1–20) |
| `--reranker NAME` | `KIKI_RAG_RERANKER` | `grader` | `grader` (main model scores each passage 0–3), `none`, or experimental `qwen3-reranker` (see the engineering log) |
| `--rerank-model NAME` | `KIKI_RAG_RERANK_MODEL` | main model | Model used by the reranker |
| `--rerank-batch-size N` | `KIKI_RAG_RERANK_BATCH` | 4 | Cap on parallel reranker requests |
| `--rerank-timeout S` | `KIKI_RAG_RERANK_TIMEOUT` | 90 | Seconds per reranker request before falling back to search order |
| `--context-characters N` | `KIKI_RAG_CONTEXT_CHARACTERS` | 7000 | Evidence characters shown to the answer model |
| `--recovery` | `KIKI_RAG_RECOVERY` | off | One rewritten-query retry when reranked evidence looks weak (experimental) |

## How well it works

Measured on October 29, 2026, on a GTX 1080 with the default models. The test
sets are small, so read these as direction rather than precision. Every number
has a receipt in [evals/receipts/](evals/receipts/rag-milestone/).

**Finding the right passage** (`kiki eval-retrieval`, 29 held-out questions:
14 written before tuning plus 15 drawn blind from random passages):

| | Keyword search | Hybrid search | Hybrid + grading |
| --- | --- | --- | --- |
| Answering passage ranked first | 7 | 11 | **19** |
| All needed passages shown to the model (top 8) | — | 20 | **26** |
| All needed passages in the top five | 12 | 17 | 25 |

**Answering questions** (`kiki eval-rag --with-model`, 18 questions):

- 15 of 15 answerable questions answered, each citing the specific passages it
  used (every citation resolves to the exact text the model was shown)
- 3 of 3 unanswerable questions correctly declined
- About **17 seconds** per document answer (about 10 with `--no-rerank`)

**Known weak spots**, in plain terms:

- **Slow.** The grading step costs about 7 seconds per question.
- **A cited answer is not always a correct one.** Kiki checks that cited
  passages were really retrieved, not that they say what the answer claims. In
  testing she occasionally added outside knowledge or credited the wrong book.
- **She does not always follow instructions.** Asked to explain SQL injection
  *without* showing an attack string, the 4B model showed one anyway, across
  three prompt rewrites. Anything that must hold is being moved into code
  rather than left to the model.
- **Some passages are never found.** In 3 of 29 held-out questions the right
  passage still misses the eight shown to the model.
- **No dedicated reranker yet.** The Qwen3-Reranker build tried so far does not
  work on this Ollama version; the main model keeps doing the grading.

The full picture, including suggestions and constraints, is in
[docs/DEVELOPMENT_NOTES.md](docs/DEVELOPMENT_NOTES.md).

## Privacy and safety by design

- **Local by default.** Models, documents, memories, and history stay on your
  machine. The only network call is the weather lookup, made to a fixed address
  the model cannot change.
- **Documents are data, not instructions.** Retrieved text is labeled
  untrusted. The grading step can only output a single digit, so a passage
  cannot talk its way into anything beyond its own score.
- **Permissions live in code.** Every tool declares a risk level. Today's tools
  are all read-only; anything that writes files, runs commands, or acts on the
  outside world must ask you first, and the model's opinion cannot change that.
- **Memory is opt-in and inspectable.** Nothing is remembered unless you ask,
  and the memory file is plain text you can edit or delete.
- **Diagnostics are filtered.** Support reports use an allowlist and never
  include environment values or conversation content.

## Project layout

```text
src/kiki/
  terminal.py        the interactive Kiki session and slash commands
  cli.py             one-off commands and evaluations
  model_client.py    the answer loop, citation checks, evidence trimming
  retrieval.py       document index, keyword search, migrations
  semantic.py        meaning-based search and hybrid merging
  rerank.py          the passage grading step
  extraction.py      turning files into citable passages
  tools.py           strictly validated tools (search, weather)
  permissions.py     tool risk levels
  memory.py          opt-in notes
  personality.py     persona file and tone settings
evals/               question sets for retrieval, answers, behavior, and code
docs/                design notes, the engineering log, development notes
tests/               110 automated tests, no network or models required
```

## Development

```powershell
pytest                                   # fast, offline
kiki --database .kiki\history.sqlite3 eval-retrieval   # passage ranking
kiki --database .kiki\history.sqlite3 eval-rag --with-model
kiki --database .kiki\history.sqlite3 eval-behavior    # refusals, tone, scope
kiki --database .kiki\history.sqlite3 eval-chat        # coding questions
```

Evaluation results are written to the ignored `evals/results/` folder.
Decisions, bugs, and trade-offs are recorded in
[docs/ENGINEERING_LOG.md](docs/ENGINEERING_LOG.md); the persona's design and
the projects it learned from are in [docs/PERSONA_DESIGN.md](docs/PERSONA_DESIGN.md).

This is a personal project, so there is no formal contribution process yet.
Issues describing a problem, with the output of `/diagnostics`, are the most
helpful thing to send.

## Roadmap

Roughly in priority order (details in the
[development notes](docs/DEVELOPMENT_NOTES.md)):

1. **Quote checking.** Anything in quotation marks must appear word for word
   in a retrieved passage.
2. **Claim checking.** Confirm each sentence is supported by the passage it
   cites, and flag or remove the rest.
3. **Rule checks in code.** When you say "don't include X", verify the answer
   instead of trusting the model.
4. **One regression gate** that runs every evaluation before a change lands.
5. **Try a larger model** for better instruction-following, within the GPU's
   8 GB.

Not planned: voice, a job engine, or controlling your mouse and keyboard.

## Acknowledgements

- [Ollama](https://ollama.com) and the [Qwen](https://github.com/QwenLM) team
  for the local models
- [Project Gutenberg](https://www.gutenberg.org) for the public-domain texts
- [Open-Meteo](https://open-meteo.com) for free weather data
- Capri Desktop, Open WebUI, and Letta for ideas about separating persona,
  memory, and rules (see [PERSONA_DESIGN.md](docs/PERSONA_DESIGN.md); no code
  was copied)
- This README follows the spirit of
  [Standard Readme](https://github.com/RichardLitt/standard-readme) and
  [Make a README](https://www.makeareadme.com)

## License

No license has been chosen yet, so all rights are reserved by default.
Third-party data and models keep their own licenses, listed in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
