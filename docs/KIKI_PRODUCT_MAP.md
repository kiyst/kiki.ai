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
