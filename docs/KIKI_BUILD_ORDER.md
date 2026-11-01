# Kiki build order

What to build in what order, and why, drafted 2026-10-31 from the product map
(`KIKI_PRODUCT_MAP.md`), the retraining plan (`KIKI_PERSONALITY_RETRAINING_PLAN.md`),
and the research notes (`research/`). A proposal for the owner to reorder.

The rule behind the order: **settle what other work depends on before building
on it.** The model choice and the instruction format shape the v2 training
data; the engine's structure shapes every tool and the user interface. Changing
any of those later means redoing work built on top of them.

## Flags (owner asked these be kept in view)

- **Licences.** Qwen is Apache 2.0. Gemma has its own terms, with conditions
  on use and redistribution that cover fine-tuned versions; check them before
  sharing a Gemma-based Kiki. (Stage 1.)
- **Gemma's Ollama leak** (about 69 MB of committed memory per request) may
  pull the llama.cpp engine switch (stage 8) much earlier, if Gemma is chosen.
- **The Python upgrade** belongs before the big refactor (stage 1), not after.
- **The model setup** is being decided now; most later stages depend on it.

## Stages

### 1. Decide (in progress)

1. Finish the model tests (chat speed, Gemma's coding run), write them up in
   `research/`, and choose the setup: voice model, technical model, or one
   model for both.
2. Check the licence terms of the chosen models for sharing Kiki later.
   Qwen is Apache 2.0; Gemma has its own terms with conditions on use and
   redistribution, including of fine-tuned versions.
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
   citation parsing, output clean-up per model.
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

### 8. Engine switch to llama.cpp's server

For per-message adapter switching on one base model (saves several GB), control
over loading and idle sleep, the chat template, and a fix or workaround for
the Ollama leak. **Move earlier if the chosen model leaks in daily use:**
Gemma's runner grows about 69 MB per request under Ollama.

### 9. Desktop interface

The sprite and its animations, the chat box, tool windows (file browser, live
terminal), the settings window and permissions page, do not disturb, idle
sleep, chimes, the paste button. Needs the engine's events (stage 2).

### 10. Installer and first-launch setup

Small installer; "setting up her brain": hardware detection, model downloads
checked against pinned hashes, profile, folders, the usage guide.

### Later

Web search (a separate decision: a new way of going online), the VS Code
extension, the optional passcode lock.

## Constraints to keep in mind throughout

- **One heavy job at a time.** Evaluations, training runs, and benchmarks
  never overlap on the GPU. Writing and reviewing data can overlap with them.
- **The owner's machine is the minimum**: 8 GB GPU, 16 GB RAM, alongside a
  browser and work software. Two models may not fit together; idle unloading
  matters; so does the leak.
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
  Check Gemma's terms before sharing a Gemma-based Kiki.

## Open decisions that block stages

| Decision | Blocks |
| --- | --- |
| Model setup (voice, technical, one or two) | 2.3, 4, 5, 7 (images), 8 |
| GUI toolkit (a new dependency) | 9 |
| Web search: whether and through which service | only itself; until then, the "fresh facts" goal and the knowledge-cutoff weakness stay open (she can read a page you link, but not look things up). When added, it needs a permissions-page entry and a tool window, both small. |
