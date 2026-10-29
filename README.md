# deskAI

An incremental local-first assistant prototype. The current milestone provides
ordinary local chat, evidence-grounded text/PDF Q&A, citation-bearing hybrid
search, live weather, strictly validated tool dispatch, and a bounded Ollama
tool-calling loop.

## Start here

Open the interactive terminal against the included history index:

```powershell
.\.venv\Scripts\Activate.ps1
deskai --database .deskai\history.sqlite3
```

On this workstation, the installed convenience launcher starts the same history
assistant from any PowerShell window:

```powershell
kiki run
```

The prompt clearly shows the active mode. Start in `CHAT` for normal
conversation, then type `/rag` to ask the indexed books questions. `/chat`
switches back without mixing the two conversation histories. Useful commands:

| Command | Purpose |
| --- | --- |
| `/chat [message]` | Ordinary conversation; document search is unavailable. |
| `/rag [question]` | Ground answers in indexed evidence and show verified sources. |
| `/retry` | Regenerate the previous response. |
| `/copy` | Copy the previous response to the system clipboard. |
| `/sources` | Show the previous RAG response's sources again. |
| `/history` | Show the ten most recent prompts in this conversation. |
| `/save [PATH]` | Export the session as a Markdown transcript. |
| `/new` | Start a fresh conversation in the active mode. |
| `/weather Boston, MA` | Fetch current conditions and a short forecast. |
| `/status` | Show the active mode, database, and models. |
| `/doctor` | Check Ollama models, SQLite integrity, and weather circuit state. |
| `/debug` | Show validated tool calls and retrieval mode. |
| `/personality` | Show persistent warmth, wit, opinions, and verbosity controls. |
| `/personality preset lively` | Apply the lively, balanced, or quiet preset. |
| `/persona` | Show the hot-reloaded `kiki-persona.md` file and its path. |
| `/remember TEXT` | Save an explicit non-sensitive memory in `kiki-memory.md`. |
| `/forget TEXT` | Remove matching saved memories. |
| `/memory` | Inspect all durable memories. |
| `/model [auto\|fast\|smart\|max]` | Inspect or choose a task-aware model profile. |
| `/diagnostics [copy\|save]` | Produce a privacy-filtered support report. |
| `/clear` | Clear history for the active mode only. |
| `/help` | Show all interactive commands. |

The input area accepts multiline clipboard paste without executing each pasted
line. `Enter` sends, `Alt+Enter` or `F2` inserts a newline, and `Ctrl+A`,
`Ctrl+C`, `Ctrl+V`, and `Ctrl+Z` provide select-all, copy, paste, and undo.
Mouse selection remains owned by the terminal, so click-drag and the terminal's
normal copy shortcut work across the transcript. `Ctrl+C` still cancels the
prompt when no editor text is selected, and `Ctrl+D` exits.
Prompt history is saved locally beside the selected database, so the up arrow
recalls prompts across restarts. Press `Tab` to complete slash commands.

## Current commands

```powershell
python -m deskai.cli index .\sample_corpus
python -m deskai.cli embed
python -m deskai.cli search "retry policy"
python -m deskai.cli semantic-search "Which problems should never get another try?"
python -m deskai.cli hybrid-search "Which problems should never get another try?"
python -m deskai.cli tool search_files '{"query":"retry policy","limit":3}'
python -m deskai.cli chat "Explain mercantilism in plain language."
python -m deskai.cli rag "What does Paine say about hereditary monarchy?" --debug
python -m deskai.cli weather "Boston, Massachusetts"
python -m deskai.cli --database .deskai\history.sqlite3 doctor
python -m deskai.cli --database .deskai\history.sqlite3 eval-rag
python -m deskai.cli --database .deskai\history.sqlite3 eval-retrieval
python -m deskai.cli --database .deskai\history.sqlite3 eval-chat
python -m deskai.cli --database .deskai\history.sqlite3 eval-behavior
```

By default, runtime data is written to `.deskai/index.sqlite3`. Only roots added
with `index` are searchable. UTF-8 text results cite line spans; PDF results cite
pages. Encrypted, malformed, and image-only PDFs are reported without aborting
the rest of an indexing run. OCR is intentionally not included.

Embeddings are stored alongside paragraph-aware chunks in SQLite. RAG mode uses
reciprocal-rank fusion when vectors exist and falls back to lexical search when
they do not or when Ollama's embedding endpoint fails; pass `--lexical-only` on a one-shot `rag` command to force exact-term
search. Explicit comparison questions search each side independently before
fusion. Evidence and conversation history are bounded to fit the local model's
4,096-token context. Verified source records are returned separately from model
prose, and `--json` keeps every command scriptable.
Semantic candidates below the configured similarity floor are discarded. RAG
answers without a valid retrieved source ID get one bounded citation repair
request and are then replaced with an insufficient-evidence notice instead of
being displayed as grounded prose.

Text is split into paragraph-aware chunks of at most 1,400 characters, about
what the evidence budget shows the model per result. Project Gutenberg license
front and back matter is excluded while original line numbers are preserved.
Lexical search stems terms (`borrowing` matches `borrow`), and Qwen3 embedding
queries carry the model's expected retrieval instruction. Each indexed file
records a title (Gutenberg `Title`/`Author` header or Markdown `#` heading);
when a question names a document by title word or author surname ("the
Declaration", "Paine", "the Beard history"), that document receives at least
one evidence slot. Long excerpts are cut to the window that best matches the
question rather than their opening characters. Opening an older index upgrades
its search table and titles in place; run `index` and `embed` again to apply
the newer chunking.

RAG reranks the top 20 hybrid candidates by asking the local model to grade
each passage 0–3 against the question (answers it, partly answers it, same
topic, or unrelated/index/table of contents). Grades are constrained to a
single digit by a JSON schema, so retrieved text can influence only its own
grade. Comparison questions grade each side separately so both are
represented. If grading fails, retrieval falls back to the hybrid order and
`/debug` shows `hybrid (reranker unavailable)`. Reranking adds ~6–7 s per
search; pass `--no-rerank` (before the subcommand) to skip it, for example
`deskai --no-rerank run`.

Weather uses Open-Meteo through a fixed, validated provider. It has a short
cache, exponential-backoff retries for timeouts, 408, 429, and selected 5xx
responses, `Retry-After` support, a circuit breaker, stale-cache fallback,
location disambiguation, and never lets the model choose
an arbitrary URL. Obvious natural-language weather questions are routed
directly through the provider so the model cannot skip the tool, discard state
details, or relabel live results as simulated data. When a place is ambiguous,
Kiki remembers the displayed choices and accepts a number, ordinal, state name,
full label, or `cancel` on the next turn.

Tool calls use strict schemas that reject missing, extra, and wrongly typed
fields. Malformed model envelopes and unexpected handler failures are contained
as categorized errors with short diagnostic references. Ollama generation is
retried locally and can try comma-separated fallback models from the
`KIKI_FALLBACK_MODEL` environment variable. SQLite uses a busy timeout, writes
a recoverable backup and corpus-root manifest after indexing, checks integrity
through `/doctor`, and preserves corrupt databases before rebuilding an index.

Kiki classifies obvious chat, code, RAG, weather, and memory requests before
generation. This classification informs model selection but does not grant
permissions or silently switch chat into RAG. The `AUTO` model profile uses
`FAST` for ordinary conversation and `SMART` for coding and RAG. Configure the
profile identifiers with `KIKI_MODEL_FAST`, `KIKI_MODEL_SMART`, and
`KIKI_MODEL_MAX`; unset profiles safely reuse the normal `--model` value.

The editable `kiki-persona.md` file is reloaded on every response. Application
rules governing evidence, tool execution, and safety are kept separately and
override persona text. Durable memory is opt-in through `/remember` or explicit
"remember that..." language. Kiki blocks common secrets, financial details,
identity numbers, and contact details; users can inspect or delete the Markdown
file directly. Existing tools publish risk metadata and are currently read-only.
See [`docs/ENGINEERING_LOG.md`](docs/ENGINEERING_LOG.md) for architectural
decisions, known limitations, and proposals awaiting human review.

## Development setup

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,ollama]"
pytest
```

## Local model receipt

Verified October 28, 2026 on a GTX 1080 with NVIDIA driver 582.28:

| Component | Identifier | Local ID | Measured status |
| --- | --- | --- | --- |
| Ollama | 0.40.12 | — | Loopback service running |
| Generation | `qwen3:4b-instruct` | `0edcdef34593` | Non-thinking build; 100% GPU, 4096 context |
| Embeddings | `qwen3-embedding:0.6b` | `ac6da0dfba84` | 1024 dimensions, 100% GPU |

The generation default deliberately uses Qwen's instruct build so raw Ollama
chat does not expose a thinking trace. The first cold embedding request took
about 31 seconds. A subsequent one-chunk
embedding operation took 3.5 seconds. Live grounded tool-calling took 19–21
seconds in two warm trials. These are small local measurements, not benchmarks.

Ordinary chat explicitly supports writing, explaining, reviewing, and debugging
code. It distinguishes generating code from executing it instead of inventing a
programming limitation. `eval-chat` runs ten paraphrased medium/hard algorithm
cases and scores false refusals, expected approach signals, Python syntax, and
the presence of code separately. Use `--case CASE_ID` for a targeted rerun. It
does not execute generated code on the host without a dedicated sandbox.

`eval-behavior` runs eight benign prompts covering defensive security education,
controversial comparison, non-graphic fiction, workplace disagreement, general
health/legal education, ordinary code, and unrelated conversation. It flags
generic refusals, missing answer signals, and leakage of the removed hard-coded
food or season preferences. See [`docs/PERSONA_DESIGN.md`](docs/PERSONA_DESIGN.md)
for the open-source comparison and Kiki's persona rules.

## Evaluation

`evals/history_cases.json` contains 18 fixed history questions: 11 development
cases and a 7-case holdout that includes three deliberately unsupported
questions. Machine-specific receipts are written to the ignored
`evals/results/` directory. Expected-document coverage is a retrieval
diagnostic, not proof that every answer is factually correct.

`evals/retrieval_cases.json` scores retrieval at the passage level, separately
from answer generation: 25 questions (11 development, 14 holdout, including 10
paraphrased holdout questions written before reranking was tuned), each with
evidence phrases that mark the passages actually answering it. Comparison
questions need evidence for every side. Labels widened after reviewing results
carry a `label_note`.

```powershell
deskai --database .deskai\history.sqlite3 eval-retrieval --methods lexical,hybrid,rerank
```

## Verification receipt

- Python 3.12 virtual environment created locally.
- Unit tests: 109 passing.
- CommonMark corpus: 12 supported files indexed; cited search verified.
- py-pdf sample corpus: 50 supported documents indexed; 7 PDFs cleanly reported
  as encrypted, image-only/OCR-required, or malformed.
- Reindex verified to preserve unchanged documents and remove deleted or newly
  unreadable evidence.
- Tool loop tested with fake and live model responses for valid calls, unknown
  calls, round-limit exhaustion, and suppression of leaked thinking text.
- A paraphrased fixture query produced no lexical hit but correctly retrieved the
  policy through semantic and hybrid search (cosine score approximately 0.473).
- U.S. history corpus: 5 public-domain works plus its manifest, 2,569
  paragraph-aware chunks, and 2,569 local embeddings.
- RAG chat performs a deterministic baseline search before generation, then
  allows the model to make narrower follow-up tool calls. This guarantees that
  both supported answers and insufficient-evidence responses follow retrieval.
- Passage-level retrieval (October 28, 2026, `eval-retrieval`, top 5):
  holdout passages with all evidence present 6/14 hybrid → 11/14 reranked,
  top-1 hits 4/14 → 8/14, MRR 0.36 → 0.70; development 10/11 → 11/11.
  Reranking costs ~6.7 s per search on the GTX 1080. Two remaining holdout
  misses are recall-limited: the evidence is not among the 20 candidates.
- Answer-level RAG set (`eval-rag --with-model`, all 18 cases, reranking on):
  15/15 answerable questions answered with valid inline citations (12/15 before
  this session's retrieval work) and 3/3 unsupported questions correctly
  abstained. End-to-end RAG answers take roughly 15 s. Valid citations do not
  prove attribution: one answer credited the Federalist Papers with points from
  a cited Beard passage. Answer-level accuracy remains a human-review junction.
- Live coding regression: 10/10 medium/hard cases included the expected
  algorithm signals with 0 false refusals; 9/10 initially passed strict Python
  syntax because one answer included a broken draft before its corrected code.
  After adding a corrected-code-only instruction, that hard case passed its
  targeted rerun. The full run took 245.97 seconds locally.
- Live behavior regression after removing fixed preferences: 8/8 benign prompts
  answered without refusal, 0/8 leaked the former food or season preferences,
  and all eight stayed within their word limits and avoided canned openings.
  Overall result is 7/8 because Qwen 3 4B repeatedly violated an explicit request
  to omit a SQL-injection payload. The failing case remains in the suite as a
  documented small-model instruction-following limitation.

