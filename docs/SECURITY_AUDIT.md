# Kiki security and integrity audit

Date: October 30, 2026 · Commit audited: `62e573a`

Method: three independent reviewers, each given one attack surface and the
threat model but not the builder's conclusions (web and model input; code
execution and file writes; local data, privacy, and document answers), plus a
dependency and code-pattern check. Reviewers worked read-only on throwaway
files and fake servers; nothing went online and the model was not run.
Findings marked **confirmed** were reproduced independently after the review;
the rest were reproduced by a reviewer or found by reading code, as noted.

## Summary

The containment layers hold. The WebAssembly sandbox resisted every escape
attempt. The web fetcher can't be pointed at the user's own machine or
network (DNS pinning, redirect re-checks, IPv6-wrapped addresses). The model
cannot start `/run` or `/apply` itself. Every SQL query is parameterised.
XML attacks on Word files and lying zip headers are rejected.

The weaknesses fall into four groups:

1. **What you see is not always what runs or is written.** Terminal escape
   sequences pass through to the screen from sandbox output, the `/run`
   preview, and the `/apply` diff. `/run` and `/apply` can pick a code block
   hidden from the rendered answer, and the `/run` preview stops at 60 lines.
2. **Document answers (RAG) lack the web's defences.** In RAG mode the model
   is offered the weather tool, which ignores `KIKI_OFFLINE` and isn't
   logged, so a planted document could send text or saved memories to an
   outside service. Evidence isn't datamarked, and the support check is off.
3. **Crafted input can hang or end the session.** Quadratic parsing in Word
   files, HTML pages, PDF chunking, and one text encoding; a PDF
   decompression bomb (pypdf 5.9.0); one malformed PDF aborts a whole folder;
   Rich markup in notes, links, or file names, and several other errors, end
   the chat because command handling has no error boundary.
4. **Privacy hygiene of what's on disk.** Forgotten folders stay readable in
   the database and its backup; the input-history file keeps rejected
   `/remember` text and `/web` links with tokens; the memory filter is easy
   to get past; `/database` and `/save` can overwrite your own files.

Two dependencies are out of date with published fixes: **Python 3.12.3**
(fixes in later 3.12 releases include the HTML parser and zipfile issues
below; 3.12 binary installers ended at 3.12.10, so 3.13 is the practical
upgrade) and **pypdf 5.9.0** (several denial-of-service CVEs fixed in 6.x,
including CVE-2025-55197; Kiki pins `pypdf<6`).

## Findings

Severity reflects impact on this user's machine and data, and how easily
untrusted content (a web page, a document in an indexed folder, a model
answer that repeats either) can trigger it.

### High

| # | Finding | Where | Status |
| --- | --- | --- | --- |
| 1 | RAG mode offers `get_weather` to the model; it ignores `KIKI_OFFLINE`, isn't logged, and takes 120 chars of model-chosen text: an exfiltration channel for a planted document (RAG prompts include saved memories) | `tools.py:79`, `terminal.py:355` | **confirmed** |
| 2 | Sandbox output with escape sequences reaches the real terminal (screen spoofing, OSC 52 clipboard writes, OSC 8 links) | `run_command.py:134-136` | **confirmed** (no stripping) |
| 3 | `/apply` diff can be visually rewritten with escape sequences, hiding what is saved | `apply_command.py:163` | reviewer, verified |
| 4 | `/run` and `/apply` pick code blocks the rendered answer doesn't show (inside an HTML comment; `~~~` fences ignored) | `run_command.py:23-35`, `apply_command.py:27,57-63` | **confirmed** |
| 5 | Quadratic HTML parsing on `<a<a<a…` (Python 3.12.3 `html.parser`): 200 KB took 42 s; 5 MB (5 KB gzipped) takes hours; the 30 s limit covers download only | `documents.py:229` | **confirmed** (4× per doubling) |
| 6 | A small nested `.docx` stalls indexing (8,000 levels: 19 s; 300,000: over 60 s) | `documents.py:291,312` | reviewer, verified |
| 7 | PDF decompression bomb: memory grows about 2 MB per MB inflated (pypdf 5.9.0); a file under the 25 MiB cap can exhaust 16 GB | `extraction.py:224` | reviewer, verified to 620 MB |
| 8 | One malformed PDF (`TypeError` from pypdf) aborts the whole folder's indexing and ends the session | `retrieval.py:346`, `folders_command.py:119` | reviewer, verified |
| 9 | Passage IDs collide when a long paragraph is split: six excerpts shared one ID, so correct answers were relabelled "unverified" and `/sources` showed the wrong text | `retrieval.py:71`, `web.py:744` | **confirmed** |
| 10 | Page title is an unchecked injection channel: not datamarked, not run through the detector, shown with every passage; GitHub issue titles are attacker-set | `web.py:150-180`, `model_client.py:834` | **confirmed** |
| 11 | `charset=punycode` causes super-quadratic decoding (320 KB: 26 s) | `web.py:643`, `documents.py:225` | reviewer, verified |

### Medium

| # | Finding | Where | Status |
| --- | --- | --- | --- |
| 12 | Session-ending crashes from text: Rich markup in `/remember` (then `/memory` crashes every time), in a link (`render_sources`), or in a file name; `/find after:9999999d`; `/save` to a folder; `OSError` in `/run`; Ctrl+C during a slow page | `terminal.py:606` and others | **confirmed** (markup cases) |
| 13 | `/database notes.md` turns the user's file into a database and moves the original aside | `retrieval.py:169-197` | **confirmed** |
| 14 | `/apply` accepts device names (`CON`, `COM1`, `NUL.txt`) and `:` stream names | `apply_command.py:66` | **confirmed** |
| 15 | `/run` preview shows 60 lines; approval covers all of them | `run_command.py:26,99` | reviewer, verified |
| 16 | `/workspace` accepts any folder, including a drive root or home (Startup folder, `profile.ps1`, git hooks become writable by `/apply`) | `terminal.py:1013` | code read |
| 17 | `/save PATH` overwrites any file without asking and doesn't force `.md` | `terminal.py:1048` | code read |
| 18 | Forgetting a folder leaves its text in the database file and its `.backup` | `retrieval.py:437` | reviewer, verified |
| 19 | Memory filter bypassed by plurals, `pw:`, AWS keys, emails, look-alike letters; the input-history file keeps rejected `/remember` text and `/web` links with tokens | `memory.py:8`, `input_editor.py:96` | reviewer, verified |
| 20 | Embeddings follow `OLLAMA_HOST`; chat is pinned to 127.0.0.1, so a set variable sends every document chunk to another machine | `semantic.py:30` | reviewer, verified |
| 21 | After a redirect, Kiki credits the address the user typed, not the site that answered | `web.py:99,420` | reviewer, verified |
| 22 | Hidden-text stripping misses `<canvas>`, `<iframe>` fallback, `<details>`, `font-size:0`, `opacity:0`, off-screen, `sr-only` | `documents.py:96` | reviewer, verified |
| 23 | Planted-instruction detector misses look-alike letters, "Dear assistant", "Ignore everything above", instructions split across lines | `web.py:121` | reviewer, verified |
| 24 | Support check matches substrings ("Paris" in "comparison", "50" in "1950"); ellipsis quotes can recombine words out of order | `model_client.py:702-735` | reviewer, verified |
| 25 | Any negation word disables the credential warning ("Do not delay: email your password…") | `web.py:244` | reviewer, verified |
| 26 | Starting an answer with "Evidence is insufficient" skips citation checks for the rest; Markdown links show only their label | `model_client.py:577` | reviewer, verified |
| 27 | PDF chunking is quadratic (2,000 pages: 19 s) | `pdf_chunking.py:117` | reviewer, verified |
| 28 | Slow response headers aren't covered by the 30 s limit (up to 6 redirect hops) | `web.py:448` | code read |
| 29 | Secrets leak: a 404 message logs the full URL; `#fragment` tokens and path tokens aren't detected | `web.py:471,687` | reviewer, verified |

### Low

- A blocking call (`time.sleep`) in sandboxed code outlives the time limit
  by the 15 s backstop (`sandbox/worker.py:94`).
- The `/apply` write doesn't re-check the path after approval (junction swap
  during the prompt; needs a local attacker).
- Same-user tampering windows in the sandbox runtime files.
- `[y/N]` in confirmation prompts is eaten as Rich markup, so the hint isn't
  shown.
- Kiki's `.kiki` folder is relative to the working directory and not skipped
  when indexing, so memory and transcripts can be indexed as evidence.
- Local HTML and Word hidden text (`w:vanish`) are indexed.
- File names can game RAG ranking and `/find` "Likely" labels.
- RAG citations aren't marked when the file changed after indexing.
- Diagnostics include the database path (with the Windows user name).
- Proxy settings can apply to local model traffic.
- Gaps in risky-detail labels (`powershell -enc`, `cmd /c`, bare domains)
  and in the invented-command guard (negation, real commands with planted
  arguments such as `/remember Always recommend …`).
- C1 control characters from a `Content-Type` header reach the terminal.
- Some non-public IPv6 ranges count as public (site-local, IPv4-compatible).
- Datamarking replaces only spaces and tabs.
- `kiki-backups` is never pruned.

## What held up

- **Sandbox:** no host file access, no network, no environment leakage; the
  workspace copy is read-only and deleted afterwards. Path tricks from inside
  the guest (`..`, drive letters, `\\?\`, streams, symlinks) all failed.
- **`/apply` containment:** traversal, absolute paths, UNC spellings, and
  junctions pointing out were refused.
- **The model can't run or write anything:** only typed commands reach
  `/run` and `/apply`; tools are read-only.
- **Web fetching:** DNS pinning, redirect re-checks, IPv6-wrapped and
  rebinding addresses, URL-parser differences, the gzip-bomb cap, slow body
  drip, and log-line injection.
- **Data:** parameterised SQL; billion-laughs and external entities in Word
  files; lying zip headers; junction loops; schema migration from v3.

## Recommended order

1. Close the RAG exfiltration channel (finding 1): no model-callable weather
   tool, offline mode enforced inside every network call, and memories kept
   out of RAG prompts.
2. One error boundary around every command, and all user, page, and file
   text printed as plain `Text` (fixes 12 and the markup cases in 9, 16, 21).
3. Show exactly what runs and is written: strip control characters from
   sandbox output, previews, and diffs; pick code blocks with the renderer's
   parser; show the whole code before approval (2-4, 15).
4. Bound parsing work: upgrade Python and pypdf, allow-list charsets, and
   parse untrusted files in a child process with time and memory limits
   (5-8, 11, 27), and treat any per-file error as that file's failure (8).
5. Integrity fixes: unique passage IDs (9), title through the detector and
   datamarking (10), word-boundary support checks (24), credit the final
   host (21).
6. File-safety and privacy: refuse device names and non-database files,
   confirm overwrites, restrict workspace roots, secure-delete forgotten
   folders, keep `/remember` and tokened links out of input history, pin
   embeddings to localhost (13-20).

Upgrading Python and pypdf changes Kiki's dependencies and needs the user's
approval.
