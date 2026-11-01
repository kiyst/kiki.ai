# Kiki build order

What to build in what order, and why, drafted 2026-10-31 from the product map
(`KIKI_PRODUCT_MAP.md`), the retraining plan (`KIKI_PERSONALITY_RETRAINING_PLAN.md`),
and the research notes (`research/`). A proposal for the owner to reorder.

The rule behind the order: **settle what other work depends on before building
on it.** The model choice and the instruction format shape the v2 training
data; the engine's structure shapes every tool and the user interface. Changing
any of those later means redoing work built on top of them.

## Flags (owner asked these be kept in view)

- **Licences: checked (2026-11-01).** Gemma 4 is standard Apache 2.0, like
  Qwen; the older Gemma Terms of Use cover earlier Gemma models only. Sharing
  a Gemma-based Kiki needs the licence copy, kept notices, and changed files
  marked. See `research/2026-11-01-gemma-licence.md`.
- **Memory growth: diagnosed (2026-11-01).** It is not a Gemma leak. It is
  the prompt cache in llama.cpp's server (which Ollama runs), growing about
  10-20 MB per new prompt in every model, up to 8 GB by default. A 256 MiB cap
  (`LLAMA_ARG_CACHE_RAM=256`, or `--cache-ram 256` when Kiki runs its own
  engine) bounds it at nearly full speed. It no longer pulls stage 8 earlier.
  See `research/2026-11-01-ollama-prompt-cache.md`.
- **The Python upgrade** belongs before the big refactor (stage 1), not after.
- **The model is decided: Gemma 4 E4B** (owner, 2026-11-01), for voice and
  technical work. Its model profile carries the cache cap.

## Stages

### 1. Decide (in progress)

1. Done: model tests written up in `research/2026-10-31-model-selection.md`;
   **Gemma 4 E4B chosen** for voice and technical work (2026-11-01).
2. Done: licence check. Gemma 4 is Apache 2.0
   (`research/2026-11-01-gemma-licence.md`).
3. Python upgrade (parked earlier): do it now, before the big refactor, not
   after.

### 2. Foundations (before any new feature)

1. **Instruction contract**: the exact format of every prompt section,
   including ones not built yet (profile, notes, her own memories, familiarity
   level, swearing setting, today's requests, danger note, chat summary, the
   note after the user's message). Frozen before v2 data is written.
2. **Engine as a local service with events**: one core (models, routing,
   tools, defences, memory) that the terminal app now, and the desktop pet,
   tool windows, and a VS Code extension later, all connect to. It reports
   what it is doing (thinking, talking, tool started or finished, idle) for
   animations and live tool windows.
3. **Model runtime behind a per-model normalization layer**: Ollama for now,
   swappable later; chat template, tool-call format, thinking switch, timeouts,
   citation parsing, output clean-up per model. Gemma's profile is decided:
   `model-profiles/gemma4-e4b.md`. **Decided 2026-11-01:** this layer
   includes a llama.cpp server runtime (local, `127.0.0.1` only) with the v2
   adapter switched on per message over one Gemma in memory, so the v2 pilot
   is evaluated on the daily setup. Gated on the trainer smoke test; fallback
   is a merged model in Ollama. The rest of stage 8 (process lifecycle, idle
   unloading, dropping Ollama) stays there.
4. **Decided routing changes**: technical work (code, documents, web, search)
   on the technical model, technical prompts without the personality layer,
   technical follow-ups kept on the technical model.

### 3. Cheap correctness features (alongside stage 4)

Calculator; clock and date maths; checks on replies; run code before showing
it (after checking which maths libraries the sandbox can run). Independent of
the personality work, small, and they fix measured failures.

### 4. v2 personality (the longest stage; runs in parallel)

1. The v2 holdout set (about 150 conversations), written before any training
   data.
2. Trainer reworked for the chosen base model and smoke-tested on the owner's
   pod with a few examples.
3. Batches of 100: drafted, validated, graded by the two reviewers, sampled by
   the owner; corrections become rules.
4. Pilot training at 500 conversations; test on Phase 0 and the holdout; blind
   review against v1; then continue toward 2,000 or change course.

### 5. Defence audit (after the model choice, alongside stage 4)

Each defence layer across several models: remove one at a time, a fresh
independently written attack set, and a look-alike set for over-blocking.
Keep what helps across models without breaking any.

### 6. Memory and chats

Profile, notes, her own memories, chat summaries and compaction, temporary
transcripts and pinned chats, memory follow-ups, warming up. Needs the engine
(stage 2) and the contract; the v2 data already uses its prompt formats.

### 7. Tools

Notes, to-do list, the timer (a separate small program), file management with
undo log and batch previews, file summaries, image understanding (depends on
the chosen model).

### 7b. Web search (approved in principle, 2026-10-31)

Users expect it from frontier assistants, so Kiki gets web search as a new way
of going online, with:

- the risks stated explicitly (on the permissions page and the first time
  it's used): what a search sends to the search service, and that results are
  untrusted;
- the defence layer extended to search: result snippets and fetched pages are
  untrusted (marked, planted lines stripped, details labelled, cited), only a
  few top results are read, every request is announced and logged, and
  `KIKI_OFFLINE` blocks it;
- a search service to choose (privacy, cost, whether a key is needed, whether
  it can be self-hosted), and what a query may contain (no names, addresses,
  or other personal details from the conversation unless the user typed them
  into the search themselves).

After the defence audit (stage 5) and the normalization layer, since search
results are the riskiest input Kiki will take in.

### 8. Engine switch to llama.cpp's server

For per-message adapter switching on one base model (saves several GB), control
over loading and idle sleep, and the chat template. Kiki then passes engine
settings such as the prompt-cache cap (`--cache-ram 256`) herself. (The
"Gemma leak" once listed as a reason to move this earlier turned out to be
that cache, fixable under Ollama too.)

### 9. Desktop interface

The sprite and its animations, the chat box, tool windows (file browser, live
terminal), the settings window and permissions page, do not disturb, idle
sleep, chimes, the paste button. Needs the engine's events (stage 2).

### 10. Installer and first-launch setup

Small installer; "setting up her brain": hardware detection, model downloads
checked against pinned hashes, profile, folders, the usage guide.

### Later

The VS Code extension, the optional passcode lock.

## Constraints to keep in mind throughout

- **One heavy job at a time.** Evaluations, training runs, and benchmarks
  never overlap on the GPU. Writing and reviewing data can overlap with them.
- **The owner's machine is the minimum**: 8 GB GPU, 16 GB RAM, alongside a
  browser and work software. Two models may not fit together; idle unloading
  matters; so does the prompt-cache cap.
- **Disk space**: about 19 GB free on C:. New models, training artifacts, and
  GGUF conversion need room; clear losing models after each decision.
- **The training-runtime contract**: once v2 data is written against the
  instruction contract, changing the prompt format means rewriting data. Freeze
  it first.
- **Human-review checkpoints**: new models or dependencies (the GUI toolkit,
  SymPy, llama.cpp), any new way of going online (web search), and tools that
  modify, run, or delete files (file management, the to-do list, the timer).
- **Decide, then build**: during review rounds, decisions are recorded and
  built afterwards.
- **Owner review time**: v2 moves at the pace of one batch of 100 per review.
- **Licences**: Capri is noncommercial; ideas only, no copied code or text.
  Gemma 4 is Apache 2.0; sharing needs the licence copy and kept notices.

## Open decisions that block stages

| Decision | Blocks |
| --- | --- |
| GUI toolkit (a new dependency) | 9 |
| Web search service and query rules (search itself approved) | only itself; until then, the "fresh facts" goal and the knowledge-cutoff weakness stay open (she can read a page you link, but not look things up). When added, it needs a permissions-page entry and a tool window, both small. |
