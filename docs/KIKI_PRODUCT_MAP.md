# Kiki product map: features and UI

A back-burner map of where Kiki is going, kept in view while designing her
architecture and modularity. Decisions here come from the owner (started
2026-10-31) and are not built yet unless marked. The engineering plan is in
`KIKI_PERSONALITY_RETRAINING_PLAN.md`.

## Who she is for

- Flagship Kiki runs on machines like the owner's or stronger (8 GB GPU,
  16 GB RAM), comfortably alongside a browser and work software.
- Users: average, semi-technical people who mostly chat; coding and research
  abilities are a reassuring extra; private and local is part of the appeal.
- For the owner first, shared later.

## How she is installed

- **For now:** developer-style (Python, git, `ollama pull`).
- **Later: a small installer, then "setting up her brain" on first launch**
  (owner, 2026-10-31). The installer only installs Kiki and her model engine
  (about 100-200 MB). On first launch, while her models download (about
  7-10 GB, with progress, pause and resume, and every file checked against a
  pinned SHA-256 hash), the user sets her up:
  - their name and city (for tooling accuracy), time zone, and units;
  - Kiki detects the hardware and chooses models and context size to fit;
  - the user picks the folders she may see and index;
  - the user gets familiar with her features, tools, and best practices from
    her usage guide while waiting.
- The same setup flow handles **model updates** later (v2, a better base),
  while Kiki herself stays untouched. Going online for downloads is said
  plainly; it is the only reason she does so unasked.
- The model line-up may end up **Gemma only** (voice and technical), depending
  on the Qwen 3.5 and Gemma test results.

## How she appears

**A desktop pet.** A small sprite in a corner of the screen, with her own
animations for speaking, using tools, and emotions.

**Chat.** Clicking her opens a small floating chat box beside her, showing the
last few exchanges. You type, she answers; casual conversation stays in that
box, with her next to it.

**Tools open their own views when that serves the task better than chat:**

| Tool | Where it shows |
| --- | --- |
| Weather and other short answers | in the chat box |
| Folders, indexing, file search, document (RAG) search | a small file-browser window: the indexed folder tree, navigable; searches started in chat show their findings and changes in it; clicking a file opens it in its normal app, as File Explorer would |
| Running and testing code | a terminal window that opens and shows live output from her sandbox runs and checks; later, a VS Code extension so she can open the project there |
| Web reading and searches | a terminal-style window showing what she fetched and found, live |
| Your profile, notes, her memories, settings | the same file-browser style window over her data folder; opening an item opens the text file to inspect or edit directly |

So: normal chat is the pet and its chat box; technical work may open the
right window for the job.

**Presence** (owner, 2026-10-31):

- She starts with Windows and sits in her corner from boot.
- A setting keeps her always on top, or lets full-screen apps cover her.
- She is also a normal app on the taskbar: clicking her there (or her sprite)
  brings her windows to the front.
- Tool windows are not always on screen like the sprite; clicking her brings
  back any tool windows that weren't closed by the user or by her.
- **Do not disturb** hides her completely until her taskbar icon is clicked.
- **Idle:** the chat box and tool windows close, she plays a sleeping
  animation, and her models go idle to give memory back (a short wake-up on
  the next message).

**Animations are status, not emotion** (owner, 2026-10-31). The sprite shows
what she is actually doing, driven by the engine's events, never inferred from
the text: idle; a subtle talking animation while she replies; a tool animation
(opening a hologram window and working in it) from a tool call until its result
is in; sleeping; and the notification mark for finished jobs and status
messages. No mood tags in her replies, and nothing for v2 to learn here.

**When she speaks first** (owner, 2026-10-31):

- A long job she was running finishes (indexing, a test run): an exclamation
  mark or similar on her sprite, and a short message ("Indexing complete").
- Automated status messages in her chat box: memory low, performance
  throttled, disk space low, or a tool failed (naming the tool).
- **To keep in mind, not decided:** unprompted memory follow-ups. During idle
  time she reviews her own memories; when something mentioned earlier is now
  due ("the interview next week"), she asks about it the next time ("So how
  was the interview?").

## The model engine

Kiki's harness is everything around the model; the engine that runs models on
the GPU is separate. Ollama is the engine today. Its drawbacks for Kiki: a
memory leak in long runs, a chat template that drops system messages after the
first, separate loads for the voice and plain models (no per-message adapter
switching on one base), and a separate install outside Kiki's control. Plan:
keep Ollama during development, make the engine swappable behind the
per-model normalization layer, and test llama.cpp's own server (which Ollama is
built on, and which Capri bundles) for the flagship installer: control over
loading and unloading, the chat template, adapter switching, and the exact
version.

## What this means for the architecture

- **One engine, several faces.** Kiki's core (models, routing, tools,
  defences, memory) runs as a local service; the sprite and chat box, the
  file-browser window, the live terminal, today's command-line interface, and a
  future VS Code extension are all clients of it. Nothing about the persona or
  the defences should depend on which face is used.
- **Events, not just replies.** The engine reports what is happening (thinking,
  speaking, a tool starting or finishing, an emotion) so the sprite can animate
  and tool windows can update live.
- **Tool views are pluggable.** Each tool declares whether its result belongs
  in chat or in a view, so new tools can bring their own window.
- **The command-line interface stays** for power users and for testing.

## Open questions

Asked one at a time; answers recorded here as they come.
