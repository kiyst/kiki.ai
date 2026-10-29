# Kiki project handoff

Last updated: October 29, 2026

## Product direction

Kiki is a general-purpose local secretary rather than a dedicated document
application. Conversation, memory, weather, document discovery, grounded
question answering, coding help, and future desktop capabilities belong to one
assistant. Document finding is an important capability, not Kiki's entire
identity.

The intended document-discovery experience is conversational. When asked to
find a file, Kiki should return several plausible candidates with calibrated
language such as:

- "This is probably the one."
- "This might be it; its name and contents both match."
- "I found a few plausible candidates. I would check these first."
- "I cannot inspect this format directly, but its filename, date, and folder
  make it a possibility."
- "I am not confident yet. Do you remember roughly when you saved it?"

Confidence wording must be based on retrieval evidence and calibrated scores,
not improvised certainty from the language model.

## Confirmed product decisions

1. Kiki remains a broad personal assistant/secretary.
2. File finding returns a conversational response followed by a few likely
   candidates rather than presenting a raw search table or claiming certainty.
3. Kiki should cover the user's normal personal folders broadly. It should not
   blindly index an entire Windows drive, because system files, caches,
   credentials, dependencies, and application data create privacy risk and
   retrieval noise.
4. A found file should be presented as a local path/link the user can choose to
   open. Kiki may summarize formats it can safely extract, but should label
   metadata-only matches honestly.
5. Images, audio, and video are priority formats after ordinary documents.
   When content cannot be inspected, Kiki should use metadata and ask useful
   follow-up questions about dates, folders, related projects, people, or
   subjects.
6. Index maintenance should become automatic.
7. The terminal remains the first interface for building and testing backend
   behavior.
8. A desktop GUI, sprite, and PC monitoring remain desired, but follow the
   difficult search/indexing capabilities.
9. Users may explicitly save folder nicknames such as "school papers" or
   "history archive." Kiki must not automatically memorize document contents.
10. Metadata should carry more weight when a query is vague or the underlying
    content cannot be parsed.
11. Voice and the job engine remain out of scope. JobGoblin may be integrated
    separately later.

## Current implementation

The repository currently provides:

- Local chat through Ollama.
- `AUTO`, `FAST`, `SMART`, and `MAX` model-profile aliases.
- A validated Open-Meteo weather tool with ambiguity handling and structured
  failures.
- Recursive selected-folder indexing for TXT, Markdown, and text-based PDFs.
- SQLite FTS keyword retrieval, local semantic embeddings, hybrid fusion, and
  model-graded passage reranking.
- Grounded document answers, source display, insufficient-evidence behavior,
  and one bounded citation-repair attempt.
- Explicit, numbered, inspectable user memories.
- Editable persona text and personality controls separated from operating
  rules.
- Separate CHAT and RAG histories.
- Transcript saving, terminal folder navigation, clipboard support, multiline
  input, diagnostics, and health checks.
- Retrieval, behavior, coding, resilience, tool-validation, and terminal tests.

Verified state at handoff:

- Canonical checkout: `C:\Users\Throw\Documents\ChatGPT\Kiki`
- Application data: `.kiki`
- Python package: `kiki`
- Distribution: `kiki-local`
- Command: `kiki`
- Git commit before this document: `2358f9b`
- Automated tests: 112 passing
- Indexed history fixture: 6 files and 2,569 passages
- Ollama generation and embedding models: installed and healthy
- Weather provider: healthy at the last live check

The previous checkout is retained temporarily because the active development
workspace holds its directory open. Once development is reopened from the
canonical Kiki checkout, the obsolete copy can be removed.

## What Capri influenced

Capri Desktop was used as a behavioral and architectural reference, not as a
code dependency. No Capri code or assets were copied.

Ideas already adopted:

- Editable persona separate from application-controlled rules.
- User memory separate from persona.
- Hot-reloaded persona text.
- Backup when resetting persona.
- A distinct assistant voice without embedding fixed tastes into every reply.

Ideas deliberately avoided:

- Dense fictional lore in every prompt.
- Repeated catchphrases and personality recaps.
- Hard-coded preferences that leak into unrelated conversations.
- Treating retrieved documents or editable persona text as operating
  instructions.

Capri's PolyForm Noncommercial licensing means future reuse must remain a
careful architectural study unless licensing is reviewed for the specific
material.

## RAG findings and current limitations

The RAG problems are not solely a generation-model constraint.

On the 14-question retrieval holdout measured October 29, 2026:

| Retrieval mode | Questions with all required evidence in the top five |
| --- | ---: |
| Keyword only | 5/14 |
| Keyword + semantic hybrid | 6/14 |
| Hybrid + model reranking (earlier measured run) | 11/14 |

This means candidate retrieval can fail before the answer model sees the
correct passage. A larger generation model may improve synthesis, tool use,
abstention, and citation formatting, but cannot answer from evidence that was
never retrieved.

Known retrieval/grounding weaknesses:

- The pipeline ranks passages when file discovery needs document-level ranking.
- Broad questions often require query decomposition and evidence from several
  passages.
- Hybrid retrieval does not consistently improve recall without reranking.
- The same small model currently helps rerank and generate answers.
- Citations identify documents more strongly than individual supporting claims.
- Citation validation checks that an identifier is real, not that every claim
  is entailed by its passage.
- Quoted text is not yet checked character-for-character against evidence.
- The 4K context budget limits how many passages can reach the model.
- Image-only PDFs are skipped because OCR is not implemented.

## Target search architecture

"Index everything" should be implemented as layered indexing rather than
running semantic extraction over an entire drive.

### Layer 1: universal file catalog

Catalog every eligible file in configured personal roots using:

- Absolute and display paths
- Filename and extension
- Parent folders and saved folder aliases
- Size
- Created, modified, and indexed timestamps
- Format-specific metadata when available
- Availability and extraction status

This layer supports files whose contents cannot yet be understood.

### Layer 2: text-content index

Extract and index text from supported documents. Search first at document level,
then retrieve passages inside likely documents for summaries or RAG answers.

### Layer 3: multimodal adapters

- Images: dimensions, EXIF, camera/date/location when available, then local
  vision descriptions and embeddings.
- Audio: tags, duration, codec, dates, then optional local transcription.
- Video: container metadata, duration, dates, optional transcription, and
  sampled keyframes later.
- STL/3D: filename/folder metadata, dimensions and geometry statistics, and a
  generated preview or specialized embedding only if justified.

Unavailable content understanding must never be presented as if the file was
actually inspected.

### Recommended default roots

- Documents
- Downloads
- Desktop
- Pictures
- Music
- Videos
- Additional folders explicitly selected by the user

Default exclusions should include operating-system directories, application
caches, browser profiles, temporary folders, dependency trees, virtual
environments, `.git`, hidden system data, and configurable private locations.

## Staged backlog

### Phase 0: housekeeping

- Reopen development from the canonical Kiki checkout.
- Remove the obsolete checkout after confirming the new command, index, and Git
  repository remain healthy.

### Phase 1: universal catalog and conversational file finding

- Add a file-level catalog schema alongside passage storage.
- Add `/find QUERY` and a typed `find_documents` tool.
- Rank whole files using filename, path, folder alias, metadata, and extracted
  content.
- Return several candidates with calibrated confidence explanations.
- Preserve the last candidate list for follow-ups.
- Render clickable paths where the terminal supports them and always provide a
  copyable path fallback.
- Add filters for folder, extension, approximate date, size, and filename.
- Add `summarize NUMBER` for extractable candidates.
- Build randomized folder fixtures and measure file recall@k, path correctness,
  confidence calibration, and stale-result rejection.

### Phase 2: folder/library management and automatic indexing

- Manage multiple roots in one library.
- Add `/folders` with add, remove, pause, resume, inspect, and reindex actions.
- Add a first-run personal-folder preset with visible exclusions.
- Implement an initial crawl, filesystem-event queue, debounce, and periodic
  reconciliation pass.
- Detect changed, deleted, renamed, and moved files.
- Keep indexing off the chat/input thread.
- Show progress, failures, last update, and pause/resume controls.
- Preserve embeddings on renames where content is unchanged.

### Phase 3: retrieval and grounding quality

- Implement hierarchical document-to-passage retrieval.
- Decompose broad and comparison questions into bounded subqueries.
- Evaluate a dedicated local reranker instead of relying only on the answer
  model.
- Use passage-specific citation identifiers.
- Verify literal quotations.
- Check sentence-level claim support and attribution.
- Add deterministic checks for explicit user constraints.
- Expand and gate the retrieval/answer evaluation suite.

### Phase 4: formats and metadata

- Plain-text source/configuration formats.
- DOCX and HTML.
- Image metadata followed by local vision indexing.
- Audio metadata followed by opt-in transcription.
- Video metadata followed by opt-in transcription/keyframes.
- OCR for scanned PDFs and selected images.
- Specialized binary/3D metadata only when it improves real test cases.

### Phase 5: safe result actions

- User-initiated open/reveal actions for validated results.
- Read bounded excerpts from selected files.
- Summarize or compare explicitly selected candidates.
- Export a result list.
- Do not autonomously move, rename, delete, edit, or execute files.

### Phase 6: desktop experience

- Desktop chat and result window using the existing backend.
- Folder/library manager and indexing progress.
- Drag-and-drop files/folders.
- System tray, quiet mode, and background status.
- Static sprite with idle, busy, replying, alert, and error states.
- Fullscreen suppression and later animation support.

### Phase 7: deferred secretary features

- Local CPU/RAM/GPU monitoring with deterministic sustained-pressure rules.
- Technology-news RSS tool.
- Packaging/installer and update strategy.
- Optional additional integrations only after explicit review.

## Upstream projects to study

Popularity counts below were observed October 29, 2026 and will change. Stars
are a discovery signal, not evidence of architectural quality.

### Open WebUI

- Repository: <https://github.com/open-webui/open-webui>
- Rough popularity at review: 157k stars
- Study: scoped knowledge bases, focused retrieval versus full context,
  filesystem-like knowledge tools (`ls`, `tree`, `grep`, `cat`), model/tool
  capability separation, and mature source UX.
- Caution: very large system; do not import its complexity wholesale.

### GPT4All

- Repository: <https://github.com/nomic-ai/gpt4all>
- LocalDocs design:
  <https://github.com/nomic-ai/gpt4all/blob/main/gpt4all-bindings/python/docs/gpt4all_desktop/localdocs.md>
- Rough popularity at review: 77k stars
- Study: folder collections, indexing progress, partially ready collections,
  local embeddings, and source disclosure.

### AnythingLLM

- Repository: <https://github.com/Mintplex-Labs/anything-llm>
- Rough popularity at review: 68k stars
- Study: desktop ingestion/collector boundaries, workspaces, document
  management, local providers, agent/tool organization, and multimodal
  ingestion.

### Khoj

- Repository: <https://github.com/khoj-ai/khoj>
- Rough popularity at review: 38k stars
- Study: general personal-assistant identity, natural-language document search,
  PDFs/Word/images, multi-interface access, custom agents, and automations.
- Product fit: the closest broad reference to Kiki's local-secretary direction.

### Jan

- Repository: <https://github.com/janhq/jan>
- Study: cross-platform desktop UX, local model installation/selection, custom
  assistants, local API boundaries, and MCP integration.
- Product fit: desktop/model-management reference rather than the primary
  retrieval reference.

### Leon

- Repository: <https://github.com/leon-ai/leon>
- Study: general personal-assistant architecture, smart/controlled/agent modes,
  layered memory, bounded proactivity, and the `Skills -> Actions -> Tools ->
  Functions` hierarchy.
- Caution: Leon 2.0 was a developer preview at review time; its newer public
  documentation was incomplete.

### Letta

- Organization: <https://github.com/letta-ai>
- Context architecture:
  <https://github.com/letta-ai/letta-code/blob/main/src/agent/prompts/letta.md>
- Study: persistent identity, current context versus durable memory, recall of
  prior conversations, inspectable memory files, compaction, and memory audits.
- Caution: Kiki should keep durable memory user-controlled rather than adopting
  aggressive automatic memory formation by default.

## Reuse policy

Before copying implementation from an upstream project:

1. Inspect the relevant code rather than relying on its README.
2. Record the exact repository commit.
3. Review the license for the specific file/component.
4. Prefer adapting an architectural pattern over copying a large subsystem.
5. Document what was reused and what was independently designed.
6. Add a focused test proving the borrowed approach fits Kiki's requirements.

## Recommended next milestone

Build Phase 1 as a terminal-first vertical slice:

> Given a randomized folder containing ordinary documents and opaque files,
> Kiki can answer "I cannot find the file about X" with three ranked file
> candidates, calibrated confidence language, valid copyable paths, and a short
> summary only when content extraction actually succeeded.

The milestone is complete only when held-out file-finding cases demonstrate
measured file recall@k and stale/deleted files are never returned as current
results.

## Approved separate milestone: coding sandbox

On October 29, 2026 the user approved a sandboxed code-execution environment
as a separate milestone, to come before Phase 1. It is specified, with its
threat model, limits, staged plan, and review checkpoints, in
[CODING_SANDBOX_HANDOFF.md](CODING_SANDBOX_HANDOFF.md). Scope: Python in a
WebAssembly sandbox (`wasmtime`), which passed its trial on October 29. Docker
and other languages are paused for a future, optional addition. Kiki targets
16 GB machines with everyday apps open. The runner, `/run`, `/workspace`, and
`/apply` are built (commit `d746cc7`).

### Paused on October 29, 2026: coding loose ends

The milestone is paused, not finished. Pick these up in order:

1. **Fix the page file, then finish the benchmarks.** Windows shrank the
   system-managed page file (commit limit 38.8 GB -> 32.9 GB), so the
   benchmark's memory guard halts runs. Recommended: a fixed page file
   (24576-32768 MB on C:) and a restart; the user has deferred the restart.
   Then resume, one at a time:
   `python evals/sandbox_trial/coding_benchmark.py leetcode --style kiki`
   (4 of 180 done), then `mbpp --style kiki` (not started). Both resume.
2. **Analyse what is already run.** HumanEval+ bare-prompt results are
   complete but not compared with the Kiki-prompt run (82.9% base, 79.3%
   plus). After LeetCode, regrade answers that import `sortedcontainers`.
3. **Commit the receipts** in `evals/receipts/coding-benchmarks/`
   (`humaneval-kiki.json`, `humaneval-bare.json`, `leetcode-kiki.json` are
   untracked; the LeetCode one is partial) with an engineering-log entry.
4. **Build the generate-test-repair loop** (stage 4 of
   [CODING_SANDBOX_HANDOFF.md](CODING_SANDBOX_HANDOFF.md)), judged against
   the finished benchmarks.
5. **Look into Ollama 0.40.12's runner memory growth** (about 35 MB per
   request; unloading resets it) and whether a newer release fixes it.

## Human-review checkpoints

Stop for review before:

- Expanding default indexing beyond normal user-library folders.
- Downloading new vision, transcription, reranking, or larger generation
  models.
- Enabling OCR or transcription by default due to resource and privacy cost.
- Adding tools that modify, move, rename, delete, or execute files.
- Adding automatic memory formation.
- Copying code from an upstream project with reciprocal or noncommercial terms.
- Beginning the desktop GUI/sprite phase.
