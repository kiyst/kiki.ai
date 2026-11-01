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

**Updates to Kiki herself: manual only** (owner, 2026-10-31). Running locally
and independently is a priority, so she never checks online for updates. New
versions exist only as releases on GitHub, published after the team's own
vetting, validation, and approval; users download them when they choose.
Beyond that, users are free to change anything in their own copy. The only
time she goes online unasked is the first-launch model download, said plainly.

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

**Commands and plain language** (owner, 2026-10-31). The slash commands stay,
but she also works out from plain language what's wanted ("what does my lease
say about pets?" searches documents; "read this: https://..." opens the page;
"find my resume" searches files) and asks when she isn't sure. That makes it
essential that every tool is highly usable and easy to call: clear, small
schemas, arguments that are easy to parse and normalize (dates, paths, "my
resume", a city), forgiving input, and a clarification question rather than a
guess when intent or an argument is ambiguous. Intent is read by the technical
model (tool planning), not by word patterns, which have proven brittle.

**Permissions page** (owner, 2026-10-31). Her settings include a page listing
each kind of action ("running code", "reading web pages", "summaries",
"logging memories", and so on), each set to manual or automatic approval,
with its risk level and the potential threats of allowing it automatically
explained beside it. Manual actions ask in the chat box with Allow / Deny and
details one click away (the code, the diff, the address). Proposal, not yet
decided: a few actions stay manual-only with no automatic option, such as
deleting or overwriting the user's files and anything that sends data
outside the computer.

**Chats** (owner, 2026-10-31; the owner entrusts the detailed architecture
to Claude when it is built). Proposed shape:

- Chats split on their own: everyday talk continues in the chat box and a new
  chat starts after a long break; work gets its own chat tied to its tool
  window (a coding session in its terminal, a document search in the file
  browser), linked from the main chat. A "New chat" button stays.
- When a chat nears 70-80% of her context, the older part is summarised in the
  background to a few hundred tokens and recent messages stay word for word; a
  quiet line marks it and the summary can be read or edited. Saving memories
  stays separate (her own memories at session end; "remember this" any time).
- Each chat keeps a title, a summary (in a separate searchable list), links to
  memories made in it, and **the full transcript, kept temporarily (about one
  to two weeks, the owner's suggestion)** so a summary that a small model got
  wrong can be checked against the real conversation, and so a vaguely
  remembered summary leads back to that exact chat. After that, the summary
  and memories remain. The user can pin any chat to a "saved by you" list,
  which keeps its full transcript and summary permanently, so Kiki can still
  trace the summary back to the whole conversation.
- Reopening a chat loads its summary and the last few messages. Finding one
  ("the chat where we fixed the Docker thing") searches titles and summaries by
  words and meaning with the existing search model.
- Summaries are written during idle time and capped, so replies never wait on
  them. Designed together with the memory system (shared background
  summarising, secrets filter, and search).

**Owner only** (owner, 2026-10-31). One person per installation. Kiki does not
try to stop someone who has physical access to the owner's computer, in the
same way a signed-in email account opens for whoever is at the device: keeping
that device secure is the owner's responsibility. The younger-user mode is
dropped for the same reason. (The passcode lock stays an optional idea in the
development notes, not a requirement.)

**Keyboard and sound** (owner, 2026-10-31). A global shortcut opens her chat
box from anywhere: Ctrl held with K pressed twice quickly (Ctrl+K, K). Note:
Discord, Slack, and VS Code use Ctrl+K themselves, so the shortcut should be
changeable in settings and should let a single Ctrl+K pass through to the app
in front. Alert chimes (a finished job, a status message) play only when her
windows aren't being looked at, with a setting to turn them off. No voice.

**What tool windows show** (owner, 2026-10-31). A setting with three levels:
*Minimal* (the result), *Steps* (the result and what she did: the page
fetched, passages picked and why, details she couldn't verify, sources), and
*Full*, the default (steps plus security events: lines removed for trying to
manipulate AI assistants, hidden text ignored, unverified contact details
flagged, sandbox limits hit). The same applies to code runs and document
searches. Showing costs almost nothing: the defences and steps run either
way, and the engine only reports what it already did (today's `/debug`,
generalised).

**Settings window** (owner, 2026-10-31). Normal settings must be readable by
an average, non-technical user from their description alone; anything else
goes in Advanced.

- **Her behaviour:** simple toggles where easy to implement: swearing on/off,
  memory follow-ups on/off, and how talkative she is (a word-count cap on
  casual replies).
- **Appearance:** sprite size, screen corner, always-on-top.
- **Folders:** which folders she can see, with their paths shown.
- **Privacy:** clear memories or chat history, how long transcripts are kept,
  and the passcode lock later.
- **Diagnostics:** a health check of the model engine, tools, and hardware,
  and the support report.
- **Advanced: hardware and models:** context size, which models she uses,
  idle time before she sleeps, redoing the hardware check. Marked plainly as
  at the user's discretion: compatibility and performance aren't guaranteed
  once changed.
- Also here: the permissions page, profile, notes, her memories, and pinned
  chats.

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
