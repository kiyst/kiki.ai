# Kiki engineering log

## 2026-10-28 — Complete Kiki namespace and data-path migration

- Renamed the Python package from its prototype namespace to `kiki`.
- Renamed the installed distribution to `kiki-local`; `kiki` is now the only
  console command.
- Moved runtime databases and configuration into `.kiki` and changed the
  default database to `.kiki/index.sqlite3`.
- Changed internal error names and the weather provider's user-agent branding.
- Made the portable `kiki.cmd` launcher resolve both the environment and data
  directory relative to its own location instead of embedding an absolute path.
- Added regression coverage for the CLI name, default path, and product text.

The outer checkout directory is controlled by the development workspace rather
than the application and is deliberately not renamed while an active workspace
is attached.

This is the human-review record for architectural decisions, known bugs,
proposals, and verified solutions. Capri is used only as a behavioral reference;
its PolyForm Noncommercial source and assets are not copied.

## 2026-10-28 — Foundation chunk

### Decisions

- Keep core services UI-agnostic and terminal-first. A GUI can consume the same
  capability, model, permission, memory, and diagnostic interfaces later.
- Do not implement a job engine; JobGoblin will remain a separate integration.
- Do not implement voice.
- Route obvious capabilities deterministically, but do not silently switch from
  chat into RAG or grant tool permission based on intent classification.
- Model profiles are configuration aliases, not hard-coded downloads. `AUTO`
  picks `SMART` for code/RAG and `FAST` for ordinary chat and tools.
- Durable memory is explicit and inspectable. No automatic harvesting from chat.
- User persona text is loaded on every turn, while operational and safety rules
  remain application-controlled and are appended after it.
- Every tool has typed risk metadata. Existing weather and retrieval tools are
  read-only; future write, execution, external-side-effect, and destructive tools
  must declare stronger policies before registration.

### Bugs and solutions

| Bug | Impact | Solution | Status |
| --- | --- | --- | --- |
| `Path.replace()` raises WinError 5 in packaged Windows test temp directories | Memory could not be saved in that environment | Use a direct UTF-8 write for the small, user-editable memory file | Fixed; regression test added |
| Small models may route obvious requests poorly | Weather or coding requests can receive generic replies | Deterministic capability classifier now informs model selection; weather remains directly routed | Fixed for current capabilities |
| Model configuration exposed only one undifferentiated model | A chat-sized model was also used for code/RAG | Added `AUTO`, `FAST`, `SMART`, and `MAX` profiles configured through environment variables | Fixed |
| Support reports risk accidentally including secrets | Bug reports could leak keys or conversations | Diagnostics use an explicit allowlist and omit environment values and conversation content | Fixed |

### Known limits

- No file-editing, command-execution, screen-control, tray, global hotkey, or GUI
  tools are registered yet.
- Model profiles do not install models and cannot know their quality; they select
  only identifiers the user configured or the existing default.
- Memory sensitivity detection is intentionally conservative but cannot identify
  every possible secret. Users can inspect or delete `kiki-memory.md` directly.
- The memory file uses a direct write due to the packaged Windows restriction;
  unlike the SQLite index, it does not yet have crash-recovery journaling.
- Capability classification is deterministic pattern matching, not a claim that
  the request has been understood semantically.

### Next proposals requiring human review

1. **Workspace tools:** read/search only first, or read plus diff-based edits in
   the same chunk? Recommended: read/search first, then staged edits.
2. **Interface:** continue terminal-first through workspace tooling, or start a
   desktop GUI shell now? Recommended: finish safe workspace boundaries first.
3. **Screen awareness:** screenshot inspection only, or full mouse/keyboard
   control? Recommended: defer control; add explicit screenshot selection later.
4. **Model discovery:** inspect locally installed Ollama models and recommend
   profiles, or also download chosen models? Recommended: discovery first and an
   explicit confirmation before downloads.

## 2026-10-28 — Persona relevance and benign refusal chunk

### Findings

- Concrete preference demonstrations caused a small model to reuse sushi and
  seasonal preferences as character lore in unrelated conversations.
- Capri's separation of editable personality, immutable operating rules, and
  user memory is useful. Its dense fictional lore and fixed tastes are not a good
  fit for Kiki's subtler assistant persona.
- Open WebUI treats persona, tools, knowledge, and parameters as separate preset
  components; Letta similarly separates self/persona from user memory. Kiki now
  follows that layered approach.

### Changes

- Removed all hard-coded food and season demonstrations.
- Reframed personality as implicit tone, judgment, curiosity, and timing.
- Added explicit relevance rules against unsolicited preferences, personality
  recaps, forced jokes, and memory recitation.
- Added instructions to answer benign analysis, drafting, coding, fiction,
  defensive education, and controversial comparison without generic refusals.
- Added an eight-case live behavior evaluation covering false refusals, answer
  signals, and legacy persona leakage.

### Boundary

Reduced conversational refusal does not alter Kiki's typed tool policies or
permission enforcement. Abliterated models are not installed or enabled by this
change.

### Live-test bug

The first behavior evaluator checked refusals and persona leakage but did not
check compliance with a prompt that explicitly excluded exploit payloads. Qwen
answered the defensive SQL-injection question, but unnecessarily supplied an
attack string. The evaluator initially reported that case as passing. The case
now checks common payload patterns, and the system prompt explicitly requires
conceptual descriptions and neutral placeholders when payloads are excluded.

After three prompt revisions, Qwen 3 4B still supplied an injection string in
that case. The final live receipt is therefore intentionally 7/8: zero false
refusals, zero persona leaks, eight content-signal passes, and one scope
violation. This remains open. Recommended solutions are a stronger instruction-
following model or a separate response verifier with bounded regeneration; do
not hide it by weakening the case.

## 2026-10-28 — RAG retrieval and grounding chunk

Baseline (`eval-rag --split all --with-model`): hybrid coverage 14/15, all
expected documents present in 13/15, answerable questions answered with valid
citations 12/15, unsupported abstentions 3/3.

### Bugs and solutions

| Bug | Impact | Solution | Status |
| --- | --- | --- | --- |
| Project Gutenberg license header/footer indexed as evidence | The Constitution's preamble chunk was ~70% license text, so its embedding described eBook licensing | Lines outside the Gutenberg START/END markers are blanked before chunking, preserving line numbers | Fixed; regression test added |
| Excerpts truncated to their first ~1,400 characters | Retrieved passages hid the answer (Article I §8 "borrow Money" began at character 2,046); the model abstained, saying the content was truncated | Chunks are now at most 1,400 characters, and longer excerpts are cut to the window that best matches the question | Fixed; regression test added |
| No stemming in SQLite FTS | "borrowing" did not match "borrow" | Schema 4 uses the `porter unicode61` tokenizer; older indexes are rebuilt in place from stored chunks | Fixed; migration test added |
| Long works crowded out short named documents | "Compare the Constitution's stated purposes…" retrieved no Constitution chunk | Documents named by distinctive title word or author surname are guaranteed one result slot | Fixed; regression test added |
| Qwen3-Embedding queries sent without an instruction | Lower semantic recall (13/15 → 14/15 at rank 5 when added) | Queries for `qwen3-embedding*` models carry the documented retrieval instruction; documents do not | Fixed |
| Grounding verifier rejected `[source: ID]` and `[source:ID, lines 3-9]` | Correct, cited answers were replaced by an insufficient-evidence notice | Citation IDs are parsed leniently; uncited answers get one bounded citation repair request | Fixed; tests added |
| Model-visible evidence carried absolute paths twice per result | Wasted context, and the model pasted full Windows paths into answers | Evidence now carries `cite`, `document` (title and filename), `location`, and `excerpt` only | Fixed |
| The model did not know which file was "the Beard history" | Abstained on a supported Beard question | Files record a title from the Gutenberg Title/Author header or Markdown H1, shown with each excerpt | Fixed; tests added |

### Result

Hybrid coverage 15/15 with all expected documents present in 15/15; mean
hybrid search 0.77 s (was 1.63 s); answerable questions answered with valid
citations 14/15; unsupported abstentions 3/3.

### Known limits

- `constitution_preamble` still abstains: the question's words ("purposes",
  "preamble") never appear in the preamble, and the 0.6B embedding model ranks
  the correct chunk outside its top 20. Not tuned away to avoid overfitting the
  evaluation set.
- Citation verification checks that cited IDs were retrieved, not that the
  cited passage supports the sentence. A model can still answer from memory
  with a valid citation.
- RAG prompts measure ~3.2–3.6k of the 4,096-token context before generation.
  No truncated answers were observed, but long answers are near the limit.
  Raising `num_ctx` to 8,192 would cost roughly 1.2 GB more VRAM on the GTX 1080.
- The eval's abstention heuristic flags some substantive answers as
  abstentions (for example `beard_suffrage`); read answers before trusting it.
- Semantic search scans every vector in Python on each query (~0.4 s for 2,569
  chunks). An in-memory vector cache or numpy would be the next speedup.
- In a live session, "Compare Hamilton's view of the judiciary with what the
  Declaration says about judges" abstained: hybrid fusion ranked the
  Declaration's signature chunk above its "Judges dependent on his Will"
  grievance, and because the Declaration was already present the named-document
  slot did not apply. In-document search alone ranks the grievance first.
- Small-model context bleed: a follow-up RAG answer repeated a caveat from the
  previous turn ("does not directly address judicial views"). `/new` clears it.

## 2026-10-28 — Passage reranking and retrieval evaluation chunk

### Why

Document-level coverage was 15/15, but a new passage-level benchmark
(`evals/retrieval_cases.json`, `eval-retrieval`) showed the passage that
answers the question reached the top five in only 13/25 cases, and 4/14 on the
holdout. With 20 candidates the evidence was present in 20/25 cases, so the
loss was mostly ranking, not recall.

### Decisions

- Pointwise graded reranking (0–3) with the installed `qwen3:4b-instruct`;
  output is a single digit constrained by a JSON schema. Rejected alternatives,
  measured on the development split only: yes/no log-probabilities (this Ollama
  build returned unnormalized values around −20 for the chosen token, and
  identical inputs scored differently) and listwise batches of six (same
  coverage, lower top-1, ~9 s). Wrapping the grade in a JSON object cost ~2x.
- 20 candidates, chosen on development results and cost. A 30-candidate pool
  would raise the recall ceiling from 20/25 to 22/25 for ~3 s more per search.
- Comparison questions grade each side's own candidates against that side, give
  each side's best passage a slot, then fill by grade.
- Reranker failure falls back to hybrid order for the whole query.
- Ten paraphrased holdout cases were written before tuning. After reviewing
  results, evidence labels were widened in four cases where unlabeled retrieved
  passages also answered the question (`label_note` in the case file); the
  label change raised hybrid scores too, and comparisons use the same labels.

### Results (top 5)

| Split | Method | Hit@1 | All evidence | MRR | Mean time |
| --- | --- | --- | --- | --- | --- |
| Holdout (14) | hybrid | 4 | 6 | 0.36 | 0.8 s |
| Holdout (14) | rerank | 8 | 11 | 0.70 | 6.8 s |
| Development (11) | hybrid | 2 | 10 | 0.46 | 0.8 s |
| Development (11) | rerank | 7 | 11 | 0.77 | 6.5 s |

End-to-end `eval-rag --with-model`: 15/15 answerable questions answered with
valid citations (was 14/15), 3/3 unsupported questions abstained.

### Known limits

- Latency: ~15 s per RAG answer (≈7 s grading, ≈8 s generation). `--no-rerank`
  restores ~9 s answers with weaker passage ranking.
- `beard_trusts` and `articles_weaknesses` remain recall-limited.
- `compare_preamble_grievances` finds the preamble but takes the Declaration's
  opening paragraph instead of a grievance.
- The reranker reads untrusted passages. Schema-constrained output limits an
  injected instruction to inflating its own passage's grade, which the answer
  model still treats as untrusted evidence.
- Attribution and embellishment are not verified. Live answers credited the
  Federalist Papers with points from a cited Beard passage and added veto and
  judicial-review details absent from the excerpts while citing valid IDs.

## RAG pipeline milestone, stage 0: frozen baseline

```text
Date: 2026-10-29
Stage: 0 (baseline before any change; docs/RAG_PIPELINE_HANDOFF.md)
Commit before change: 0e74d06
Files changed: docs/RAG_PIPELINE_HANDOFF.md (added), evals/receipts/rag-milestone/00-*
Behavior changed: none
Tests/evaluations run: kiki eval-retrieval (all 25 cases, lexical/hybrid/rerank, k=5)
Result: holdout full-evidence@5 lexical 5/14, hybrid 6/14, rerank 11/14;
        hit@1 1/14, 4/14, 8/14; MRR 0.196, 0.360, 0.696;
        rerank mean 6.7 s per query (hybrid 0.74 s). Matches the historical
        table exactly; no environmental difference to explain.
Known bugs: as listed in the previous entry (beard_trusts, articles_weaknesses
        recall-limited; compare_preamble_grievances ranking).
Decision or proposal: receipts for this milestone live in evals/receipts/
        (evals/results/ is gitignored). Peak VRAM was not sampled for the
        baseline; later stages add a sampler.
Human review needed: none for this stage.
```

Corpus identity `2161829777560d6b` (6 files, 2,569 passages, all embedded);
Ollama 0.40.12; model digests `qwen3:4b-instruct` 0edcdef34593,
`qwen3-embedding:0.6b` ac6da0dfba84. Full metadata:
`evals/receipts/rag-milestone/00-baseline-environment.json`.

## RAG pipeline milestone, stage 1: configurable retrieval settings

```text
Date: 2026-10-29
Stage: 1 (retrieval settings and reranker interface)
Commit before change: 0eb8369
Files changed: src/kiki/settings.py (new), rerank.py, semantic.py, retrieval.py,
        model_client.py, cli.py, terminal.py, diagnostics.py, retrieval_evals.py,
        tests/test_settings.py (new), tests/test_rerank.py, README.md
Behavior changed: none at defaults. New: candidate count, final passages,
        reranker (grader|none), rerank model, batch cap, timeout, and answer
        context budget are configurable via KIKI_RAG_* or CLI flags, validated
        with errors that name the setting, and shown in /diagnostics, /status,
        and /doctor (rerank model installed/missing). Rerankers share a
        `Reranker` protocol; results record `ranker` (which stage produced the
        score). Retrieval mode now names the reranker: "hybrid + rerank (grader)".
        Retrieval receipts add any-evidence@k, per-case rerank latency, fallback
        count, wall time, whole-GPU idle/peak memory, git commit and dirty files,
        corpus identity, case-file hash, and Ollama model digests.
Tests/evaluations run: pytest 131 passed (19 new); eval-retrieval holdout at
        defaults (evals/receipts/rag-milestone/01-config-defaults-holdout.json)
Result: holdout full@5 lexical 5/14, hybrid 6/14, rerank 11/14; hit@1 1/4/8;
        MRR 0.196/0.360/0.696 - identical to baseline, and every case's top-5
        list is identical for every method. Rerank 6.6 s per query of 7.4 s.
        GPU memory: 2,485 MiB idle, 6,914 MiB peak of 8,192 (whole device).
Known bugs: rerank_batch_size is accepted and reported but the grader scores
        sequentially; it takes effect with a batch-capable reranker. GPU memory
        is whole-device, so other applications inflate it.
Decision or proposal: lexical/semantic internal limits raised from 20 to 100
        for candidate experiments; BM25 window formula unchanged for k <= 20.
        The search_files tool limit stays capped at 20.
Human review needed: before stage 2 (see report: model download already done,
        and a dedicated reranker adds ~0.7 GB GPU memory with ~1.3 GB headroom).
```

## RAG pipeline milestone: expanded blind holdout

```text
Date: 2026-10-29
Stage: evaluation set expansion (before stage 2 experiments)
Commit before change: a779dcc
Files changed: evals/retrieval_cases.json (+15 holdout cases),
        evals/receipts/rag-milestone/02-expanded-holdout-baseline.json
Behavior changed: none (evaluation data only)
Tests/evaluations run: eval-retrieval --split holdout at default settings
Result (29 holdout cases, top 5):
        lexical full 12, any 14, hit@1 7, MRR 0.336, 0.05 s
        hybrid  full 17, any 18, hit@1 11, MRR 0.467, 1.0 s
        grader  full 25, any 26, hit@1 19, MRR 0.757, 6.9 s (6.3 s reranking)
        Blind 15 alone: lexical 7, hybrid 11, grader 14 full@5.
        The original 14 are unchanged (grader 11/14). GPU 2,352 idle / 6,842 peak MiB.
Known bugs: none new.
Decision or proposal: cases were drawn with random.Random(20261029) from
        passages of at least 700 characters (excluding contents, index, and
        question lists), at most three per work, and questions were written
        from the passage text before any new configuration ran. Evidence
        phrases were checked to exist in the corpus; no labels were adjusted
        after seeing retrieval results.
Human review needed: none.
```

## RAG pipeline milestone, stage 2: dedicated reranker behind a feature flag

```text
Date: 2026-10-29
Stage: 2 (dedicated reranker; experimental)
Commit before change: 215a034
Files changed: src/kiki/rerank.py, settings.py, cli.py, tests/test_rerank.py,
        tests/test_settings.py
Behavior changed: none at defaults (reranker stays `grader`). New opt-in
        `--reranker qwen3-reranker` / KIKI_RAG_RERANKER=qwen3-reranker and an
        eval-retrieval method of the same name. Qwen3Reranker scores
        P(yes)/(P(yes)+P(no)) from Ollama raw /api/generate log-probabilities
        using the published Qwen3-Reranker prompt; bounded concurrency
        (rerank_batch_size), explicit per-request timeout, LRU score cache,
        structured KikiError for timeouts, missing model (with the
        `ollama pull` command), malformed or non-yes/no output, and flat
        distributions; chat-template control tokens are stripped from
        untrusted text before building the raw prompt. Any failure falls back
        to fused order and `ranker` records "fused".
Tests/evaluations run: pytest 143 passed (12 new reranker tests with a fake
        client); fidelity probe; eval-retrieval holdout hybrid vs qwen3-reranker.
Result: the installed model is unusable. dengcao/Qwen3-Reranker-0.6B:Q8_0
        (a repackaged mradermacher GGUF) returns a flat distribution on
        Ollama 0.40.12 - every token logprob -11.929 = ln(1/151,936) - for
        the reranker prompt, a plain completion, and CPU-only inference.
        Live run: 29/29 queries fell back cleanly ("hybrid (reranker
        unavailable)"), full@5 17/29 like hybrid; hit@1 10 vs 11 because the
        fallback pool fuses 20 per list where plain hybrid fuses 15.
        The model occupies 1.13 GB of VRAM when loaded.
Known bugs: no working dedicated reranker on this machine. Ollama
        log-probabilities themselves are sound (qwen3:4b-instruct: "Yes" at
        -4.7e-05 for a true statement), so the adapter is not the cause.
Decision or proposal: keep the grader as default; keep Qwen3Reranker as an
        experimental adapter. Options needing approval: (a) a different GGUF
        conversion of Qwen3-Reranker-0.6B; (b) llama.cpp server's rerank
        endpoint (new runtime); (c) torch + sentence-transformers as Zotero
        RAG uses (several GB). Zotero RAG's reranking.py was studied
        (rhenryliu/zotero-rag a9f308d, MIT) for design only - fallback to
        vector order and calibrated min/soft score bands; no code copied.
Human review needed: yes - the model was downloaded before the review rule
        was set, has been verified broken, and any working alternative needs
        a new download or runtime.
```

## RAG pipeline milestone, stage 3: candidate and context experiments

```text
Date: 2026-10-29
Stage: 3 (controlled experiments; one setting changed per run)
Commit before change: d26afeb
Files changed: src/kiki/settings.py (default passages 5 -> 8), README.md,
        tests/test_settings.py, evals/receipts/rag-milestone/04-*, 05-*
Behavior changed: the answer model now receives 8 passages instead of 5,
        within the unchanged 7,000-character evidence budget (each passage's
        focused window shrinks from up to 1,400 to about 875 characters).
        eval-retrieval scores top-8 by default now; pass --limit 5 to compare
        with earlier receipts.
Tests/evaluations run: eval-retrieval holdout (29 cases) for candidates
        20/32/50 at 5 passages and 20 at 8 passages; eval-rag --with-model
        (18 cases) at 5 and 8 passages; pytest 143 passed.
Result (grader reranker, holdout 29):
        | Candidates | Passages | Full | Any | Hit@1 | MRR   | Query time |
        | 20         | 5        | 25   | 26  | 19    | 0.757 | 6.9 s      |
        | 32         | 5        | 26   | 27  | 18    | 0.716 | 10.1 s     |
        | 50         | 5        | 25   | 26  | 16    | 0.668 | 15.6 s     |
        | 20         | 8        | 26   | 26  | 19    | 0.757 | 6.5 s      |
        | none (20/8 hybrid)  | 8        | 20   | 20  | 10    | 0.456 | 0.7 s      |
        Per-case: 32 and 50 both rescue beard_trusts but lose top-1 on
        new_revenue_bills; 50 also loses top-1 on new_officials_swarm and
        blind_independent_powers and drops new_time_to_part from the top 5.
        8 passages adds compare_preamble_grievances (a long-standing miss).
        Answers (15 answerable + 3 unsupported): 5 passages 14/15 answered
        with valid passage citations (abstained on compare_preamble_grievances),
        3/3 abstained; 8 passages 15/15 and 3/3. Generation 8.1 s -> 9.6 s.
        Reranking memory is unchanged (same model); GPU peak stays ~6.9 GB.
Known bugs: a larger pool hurts the 0-3 grader - more distractors tie at
        the top grade and ties fall back to fused order. A finer-grained
        reranker would be needed to benefit from 32-50 candidates.
Decision or proposal: default 20 candidates / 8 passages. Rejected 32
        (+1 full, -1 hit@1, +46% latency) and 50 (no recall gain, -3 hit@1,
        +126% latency). Caveat: the 8-passage gain is one case of 29 for
        retrieval and one of 15 for answers - direction, not proof - but no
        metric regressed. The 4K context did not prevent a fair 5-vs-8
        comparison because both runs share the same evidence budget.
Human review needed: no.
```

## RAG pipeline milestone, stage 4: PDF passages across page breaks

```text
Date: 2026-10-29
Stage: 4 (PDF chunk continuity)
Commit before change: 5d0addb (developed on branch rag-stage4-pdf from d26afeb)
Files changed: src/kiki/pdf_chunking.py (new), extraction.py, retrieval.py,
        retrieval_evals.py, THIRD_PARTY_NOTICES.md, tests/test_pdf_chunking.py
Behavior changed: PDFs are chunked as one document-order paragraph stream to
        the text budget (1,400 characters) with one-paragraph overlap. A
        sentence or paragraph cut by a page break is joined (de-hyphenated);
        each passage stores start and end page, and split pieces report only
        the pages they contain. Repeated running headers/footers and bare page
        numbers are stripped (never emptying a page). Blank, image-only, and
        unreadable pages are skipped; a PDF with no text still reports the OCR
        limitation. PDF extraction has its own version (pdf-continuous-v1), so
        existing PDFs are re-extracted the next time their folder is indexed,
        while text files keep their source IDs and embeddings.
Tests/evaluations run: pytest 157 passed (14 new, with generated PDF fixtures:
        sentence split across pages, paragraph split across pages, hyphenation,
        repeated headers/footers, blank page, image-only page, malformed PDF,
        partially readable PDF, budget and page-order invariants). Old vs new
        extraction over test-data/pdf-samples (35 PDFs). Fresh re-index of the
        history corpus with the new code.
Result: pdf-samples - same 7 failures as before (1 encrypted, 5 no text,
        1 unreadable), no crashes; passages 282 -> 310, 73 now span two pages,
        maximum passage 3,953 -> 1,398 characters (now within budget).
        History corpus: identical identity 2161829777560d6b and all 2,569
        passages byte-identical, so holdout retrieval results are unchanged by
        construction; the holdout eval was not re-run for this stage.
Known bugs: no labeled PDF retrieval set exists yet, so PDF retrieval quality
        is unmeasured. Heuristics (header detection, continuation joining) are
        tuned on synthetic fixtures; unusual layouts (multi-column, tables)
        may join or split imperfectly. A continuation that starts with a
        capital letter is deliberately not joined.
Decision or proposal: adapted from Zotero RAG (rhenryliu/zotero-rag a9f308d,
        rag/chunking.py chunk_document and _hard_split, MIT); notice and full
        license text in THIRD_PARTY_NOTICES.md. Changed: overlap keeps whole
        paragraphs with their own pages (upstream mis-attributes the carried
        tail), plus joining, page maps, and header removal.
Human review needed: no (re-extraction of PDFs happens only when the user
        re-indexes a folder; nothing is rebuilt automatically).
```

## RAG pipeline milestone, stage 5: passage-level citations

```text
Date: 2026-10-29
Stage: 5 (citations resolve to specific passages)
Commit before change: eb9af2d (developed on branch rag-stage5-citations)
Files changed: src/kiki/retrieval.py, model_client.py, evals.py,
        tests/test_model_client.py
Behavior changed: each passage has a stable ID, "p" + 11 hex characters of
        sha256(document ID, location kind, start, end). It is derived from
        stored fields, so existing indexes need no migration, and it changes
        whenever the file content or extraction changes. The model sees
        `cite: [source:<passage ID>]`, the document title/filename, and the
        location, never the path or document ID. Only passages actually shown
        within the evidence budget are citable. Each source record holds the
        passage ID, document ID, path, display name, location kind/start/end,
        and the exact evidence text supplied to the model, so later quote and
        claim checks can compare against it. Document-level and unknown IDs
        fail validation; `resolve_citations` maps an answer's citations to
        records and marks unknown IDs as unresolved rather than dropping them.
        Citations display as "lines 190-246", "page 3", or "pages 3-4".
Tests/evaluations run: pytest 161 passed (5 new); eval-rag --with-model at the
        new defaults (20 candidates, 8 passages).
Result: 15/15 answerable questions answered with valid passage citations,
        3/3 unsupported questions abstained (receipt 06). Every cited ID in
        every answer resolved to a shown passage. Mean answer time 10.5 s
        (9.6 s in stage 3's 8-passage run; within run-to-run variation of
        the citation-repair retry, which is not separately counted yet).
Known bugs: validation proves a citation points at real shown evidence, not
        that the evidence supports the sentence; quote and claim checks
        remain future work (handoff Phase 3).
Decision or proposal: no schema change. Passage IDs are not stored, so a
        re-chunked file gets new IDs; saved transcripts keep the citation
        text, which names the file and span, so they stay readable.
Human review needed: no.
```

## RAG pipeline milestone, stage 6: bounded retrieval recovery

```text
Date: 2026-10-29
Stage: 6 (one deterministic recovery pass owned by the retriever)
Commit before change: 6b77ce2 (developed on branch rag-stage6-recovery)
Files changed: src/kiki/semantic.py, settings.py, cli.py, terminal.py,
        retrieval_evals.py, tests/test_recovery.py (new), tests/test_settings.py
Behavior changed: none by default. With --recovery / KIKI_RAG_RECOVERY=on,
        if the best reranked score is below the reranker's strong threshold
        (grader 2, Qwen3 0.5), the retriever runs one retry with no model
        call: a search restricted to documents named in the question, a
        keyword rewrite keeping names and quoted phrases, and up to two parts
        of an "X and Y" question. New candidates are taken round-robin across
        rewrites (so a late sub-question is not starved), capped at half the
        first-pass budget (minimum 4), scored against the original question,
        and merged on the same score scale. Comparisons skip it (already
        decomposed). Any failure falls back to fused order. Receipts record
        each recovery (trigger score, queries, new candidates, improved).
Tests/evaluations run: pytest 168 passed (7 new, including a corpus where only
        the sub-question finds the answer and a test that exposed the
        starvation bug fixed by round-robin); eval-retrieval at defaults with
        recovery off and on, holdout 29 and development 11.
Result: recovery triggered on 0 of 40 questions. Holdout full@8 26/29,
        hit@1 19, MRR 0.757 both ways; development 11/11. Latency unchanged.
        The three remaining misses (beard_trusts, articles_weaknesses,
        blind_senate_tyranny) never look weak: the grader gives a wrong
        passage a 2 or 3, so the trigger cannot see them.
Known bugs: the trigger depends on calibrated reranker scores, which the
        coarse 0-3 grader does not provide on this corpus.
Decision or proposal: keep recovery off by default. Lowering the trigger
        (e.g. "no passage graded 3") was not tried because it could only be
        tuned on the holdout set. A calibrated dedicated reranker is the
        natural trigger; revisit once one runs on this machine.
Human review needed: no.
```

## RAG pipeline milestone, stage 2 follow-up: llama.cpp reranker

```text
Date: 2026-10-29
Stage: 2 follow-up (dedicated reranker via an approved alternative runtime)
Commit before change: 6e761d0
Approval: option (a) "a different GGUF of Qwen3-Reranker-0.6B", falling back
        to option (b) "llama.cpp server", both approved by the user.
Files changed: src/kiki/rerank.py (LlamaCppReranker), settings.py
        (llama-cpp reranker, rerank_url restricted to loopback), cli.py
        (--rerank-url, llama-cpp eval method), terminal.py (/doctor checks
        the reranking server), tests/test_rerank.py, tests/test_settings.py,
        evals/receipts/rag-milestone/08-*
Behavior changed: none by default (grader stays). Opt-in
        `--reranker llama-cpp` posts candidates in chunks of 10 to
        http://127.0.0.1:8081/v1/rerank (bounded concurrency, explicit
        timeout, control tokens stripped, every index validated). Unreachable
        server, HTTP errors, timeouts, and malformed or partial results raise
        structured errors and fall back to fused order. Non-loopback or https
        URLs are rejected so queries stay on this machine.
Downloads: ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF (repo sha a02f48bb,
        file sha256 22c9979c..., 639 MB, Apache-2.0) via Ollama; Ollama
        reports it "does not support generate" (pooling/rank model), so (a)
        failed. llama.cpp b11979 (commit bf48103ad, MIT) Windows CPU and
        Vulkan builds, sha256 matched GitHub release digests, installed under
        %LOCALAPPDATA%\kiki\llama.cpp\ (outside the repo). llama-server
        loads the same GGUF blob from Ollama's store; no further model
        download. Not a Python dependency.
Tests/evaluations run: pytest 182 passed (14 new); probe (capital of China:
        Beijing 0.9997, Paris 0.0002, gravity 5e-6); eval-retrieval holdout
        and development.
Result (holdout 29, 8 passages):
        | Reranker            | Candidates | Full | Hit@1 | MRR   |
        | grader (default)    | 20         | 26   | 19    | 0.757 |
        | llama-cpp           | 20         | 25   | 17    | 0.694 |
        | llama-cpp           | 32         | 25   | 17    | 0.695 |
        | llama-cpp           | 50         | 25   | 17    | 0.691 |
        | llama-cpp+recovery  | 20         | 25   | 17    | 0.694 |
        Development 11: both 11/11 full; hit@1 llama-cpp 8 vs grader 7.
        Blind 15: tie, 14/15 full and 11 hit@1.
        Latency: CPU (Ryzen 5 3600) 36.8 s reranking per question vs the
        grader's 6.6 s; Vulkan GPU 3.7-8.8 s per 20 passages in isolated
        timing. Later GPU timings in receipts 08-c32/c50/recovery/development
        are NOT valid - see incident below. Accuracy is unaffected because
        scoring is deterministic. Memory: CPU server peak 1.36 GB RAM; Vulkan
        server pushed whole-GPU use to 7.7-7.8 GB of 8 GB beside Ollama.
Known bugs: recovery never triggered with llama-cpp either; its first-pass
        scores were already >= 0.5 in the remaining misses.
Decision or proposal: the dedicated reranker does not meet the handoff bar
        (beat or meaningfully match 26/29 at lower cost): -1 full, -2 hit@1,
        and slower or memory-risky on this machine. Keep the grader as default;
        keep llama-cpp as an experimental opt-in. Remaining dedicated-reranker
        options would be the CUDA build (faster, ~0.7 GB VRAM, same memory
        risk) or a different model; neither is proposed now.
Incident: the PC ran out of virtual memory around 03:50 and was restarted
        at 03:55. Windows Resource-Exhaustion-Detector named a llama-server
        process (11.9 GB committed and growing), Fusion 360 (8.3 GB), and
        another llama-server (2 GB). Cause: when switching from the CPU to the
        Vulkan server, the evaluation's Python processes were stopped but not
        the shell loop that launched them, so its remaining runs continued
        against the new server while a second evaluation chain started - two
        chains plus Ollama plus the Vulkan server on a 16 GB RAM / 8 GB VRAM
        machine already under pressure. No data was lost.
        Rules adopted: one heavy job at a time; stop the whole background
        task (not just child processes) and confirm nothing remains before
        starting another; do not run a GPU reranker beside Ollama on this
        card; close large applications during long evaluations.
Human review needed: no further action proposed.
```

## RAG pipeline milestone: completion review

```text
Date: 2026-10-29
Stage: close-out against docs/RAG_PIPELINE_HANDOFF.md completion criteria
Files changed: src/kiki/terminal.py, self_knowledge.py, tests/test_terminal.py
Behavior changed: the sources table now lists only the passages the answer
        cites, in citation order, and counts the uncited retrieved passages;
        `/sources all` lists every retrieved passage. An answer with no
        resolvable citation says so instead of implying all were used.
Tests/evaluations run: pytest 183 passed (1 new). No model evaluation:
        display-only change.
```

| Criterion | Status | Evidence |
| --- | --- | --- |
| 1. Original evaluation reproducible | Met | Receipts 00 and 01: identical top-5 lists for every case and method |
| 2. Settings configurable and diagnosable | Met | `settings.py`, `/diagnostics`, `/status`, `/doctor`; tests in `test_settings.py` |
| 3. Dedicated reranker evaluated against the grader | Met, did not win | Receipts 03 (Ollama builds unusable) and 08 (llama.cpp: 25/29 vs 26/29) |
| 4. Candidate/context experiments with receipts | Met | Receipts 04, 05, 08 |
| 5. PDF passages cross pages with provenance | Met | `pdf_chunking.py`; 14 fixture tests; sample-corpus comparison |
| 6. Citations resolve to specific passages | Met | Receipt 06: every cited ID resolved; `resolve_citations` |
| 7. Reranker failure keeps grounded answers | Met | Live fallback on 29/29 (receipt 03-holdout); fallback tests for every reranker |
| 8. Tests pass, focused tests added | Met | 183 passing (112 at milestone start) |
| 9. Documentation of defaults, rejections, bugs, tradeoffs | Met | Stage entries above; README configuration and results; DEVELOPMENT_NOTES |

Known gaps carried forward: GPU-reranker latency in receipts 08-c32, c50,
recovery, and development is invalid (overlapping runs, see incident);
three holdout misses remain; no labeled PDF retrieval set; citations are
not yet checked for claim support; recovery has never triggered.

## Coding sandbox milestone, stage 1: backend trial

```text
Date: 2026-10-29
Stage: 1 (setup and backend trial), per docs/CODING_SANDBOX_HANDOFF.md
Commit before change: bb70096
Files changed: evals/sandbox_trial/ (new trial harness), evals/receipts/
        sandbox-trial/wasm-trial.json, pyproject.toml (`sandbox` extra:
        wasmtime==50.0.1), THIRD_PARTY_NOTICES.md, README.md, docs/
        CODING_SANDBOX_HANDOFF.md, docs/PROJECT_HANDOFF.md
Outside the repo: wasmtime in .venv; CPython 3.14.9 WASI build in
        %LOCALAPPDATA%\kiki\wasi-python\3.14.9 (zip sha256 8de78341...29dfa2);
        %USERPROFILE%\.wslconfig created (2 GB, 2 processors, swap 0)
Behavior changed: none in Kiki itself; no execution path is wired up.
Tests/evaluations run: WebAssembly trial (14 scenarios, 10 warm runs, 3
        compute runs, native reference); pytest 183 passed.
Result: WebAssembly passed every check. Warm run 0.35 s, 57 MB per run,
        2.3x slower than native, all isolation and limit probes held.
        Docker trial not run: 2.3 GB commit headroom with everyday apps open,
        and Docker Desktop needs about 3 GB.
Known bugs: fixed during the trial, a 10 s deadline ran 15.4 s because
        Windows timer granularity stretched 10 ms epoch ticks; now one tick
        at the deadline.
Decision: Python through WebAssembly is the sandbox. Docker and other
        languages are paused for a future, optional, opt-in addition. Kiki
        targets 16 GB machines with everyday apps open.
Human review needed: stage 0 benchmark problems and hidden tests; enabling
        /run (checkpoint 7).
```

Before the trial the PC had 31.8 GB committed of a 34.2 GB limit, mostly
VS Code, browsers, and Electron apps. That, not Kiki, is the binding
constraint on a 16 GB machine, and it is why the decision favors the backend
that adds tens of megabytes instead of gigabytes.

## Coding sandbox milestone: benchmark harness

```text
Date: 2026-10-29
Stage: 0/3 groundwork (standardized benchmarks instead of hand-written
        problems, at the user's request), per docs/CODING_SANDBOX_HANDOFF.md
Commit before change: 6b55783
Files changed: evals/sandbox_trial/coding_benchmark.py, benchmark_selftest.py,
        evalplus_mbpp.py (adapted, Apache-2.0), README.md (new),
        wasm_worker.py, wasm_trial.py; evals/receipts/coding-benchmarks/
        reference-selftest.json; THIRD_PARTY_NOTICES.md; README.md
Behavior changed: none in Kiki itself. The trial worker now uses a 2 MiB
        wasm stack on a 16 MiB host thread and reports the trap cause.
Tests/evaluations run: official solutions graded in the sandbox
        (HumanEval+ 163/164, MBPP+ 376/378, LeetCode 161/180); trial limit
        probes rerun after the stack change (all held); pytest 183 passed.
Result: harness validated. Model runs (HumanEval+ with and without Kiki's
        prompt, LeetCode Medium/Hard, MBPP+) were started and are not yet
        complete; results will be logged in a separate entry.
Known bugs: harness bugs found and fixed by the self-test: MBPP+ tuples and
        complex numbers arrived as lists and strings (now restored with
        EvalPlus's own code); "not None" oracle compared match objects
        instead of booleans. Sandbox limits found: @cache recursion trapped
        below 500 levels (now ~1,200 per call; an earlier
        "~3,000" figure was mis-measured, see the sandbox-into-Kiki entry); 32-bit size overflow on very large
        ints; one WebAssembly float difference; no sortedcontainers.
Decision or proposal: bundle sortedcontainers (pure Python, Apache-2.0,
        pinned, read-only) because LeetCode's own environment provides it;
        awaiting approval and the count of model answers that import it.
Human review needed: the sortedcontainers proposal (checkpoint 10).
```

## Coding sandbox milestone, stage 2: the sandbox inside Kiki

```text
Date: 2026-10-29
Stage: 1 (remaining) and 2 (runner), per docs/CODING_SANDBOX_HANDOFF.md
Commit before change: 770adc8
Files changed: src/kiki/sandbox/ (new: runtime, limits, staging, jobs, wasi,
        worker, runner, preflight, setup), src/kiki/cli.py (`kiki sandbox
        setup|doctor`), pyproject.toml (wasmtime required), tests/
        test_sandbox.py (new), README.md, THIRD_PARTY_NOTICES.md, docs
Behavior changed: `kiki sandbox setup` prepares the pinned runtime and
        records checksums; `kiki sandbox doctor` checks it and runs a test
        program. Nothing in chat can execute code yet.
Tests/evaluations run: pytest 211 passed (28 new). Real setup on this PC
        reused the trial's verified archive (no download); doctor test run
        0.71 s, 78 MB.
Result: the trial's design now lives in Kiki, with three changes:
        the compiled runtime is checksum-verified before every run (wasmtime
        deserialization skips validation); leftover-folder cleanup only
        touches folders older than 15 minutes, so it cannot delete a run in
        progress; the launcher puts /input on sys.path so multi-file
        programs can import each other.
Known bugs: correction. The trial's "~3,000 levels" for memoized recursion
        was mis-measured (cached calls at rising depths each descended at
        most 1,000 new levels). Measured per call: 1,200 passes, 1,500 traps;
        the 512 KiB default traps below 500. Plain recursion passes 100,000.
        Docs corrected.
Decision or proposal: `/run` (checkpoint 7) is next once reviewed.
Human review needed: checkpoint 7 (enable /run); sortedcontainers proposal.
```

Also found while the benchmarks ran: Ollama 0.40.12's runner grew from
4.4 GB to 11.3 GB of committed memory over about 250 requests (working set
3.2 GB), and unloading it returned 6 GB. The benchmark now unloads the model
every 40 problems. The C: drive has 27.7 GB free, which limits how far
Windows can grow the page file; together these explain the memory-guard
stops and likely the October 29 crash.

## Coding sandbox milestone, stage 5: `/run` and sortedcontainers

```text
Date: 2026-10-29
Stage: 5 (terminal workflow, /run only) and checkpoint 10 (one package)
Commit before change: 693533c
Files changed: src/kiki/run_command.py (new), terminal.py, self_knowledge.py,
        src/kiki/sandbox/ (packages grant, memory-headroom refusal),
        tests/test_run_command.py (new), tests/test_sandbox.py, README.md,
        THIRD_PARTY_NOTICES.md, docs/CODING_SANDBOX_HANDOFF.md
Behavior changed: `/run` runs the last answer's Python, `/run FILE.py` a
        copy of a file, after a preview and [y/N] confirmation. The sandbox
        refuses to start when Windows cannot promise worker memory plus
        512 MB. sortedcontainers 2.4.0 is importable, read-only, from
        /packages. Kiki's self-description says how /run works and that she
        cannot run code herself.
Tests/evaluations run: pytest 227 passed (16 new), including a real
        end-to-end /run and a read-only check on /packages; `kiki sandbox
        setup` and `doctor` on this PC.
Result: users can run Kiki's Python safely; the model has no path to
        trigger execution.
Known bugs: none found. /apply (persistent edits) is not built.
Decision or proposal: the benchmark keeps grading in its own trial
        environment until LeetCode finishes, then answers that import
        sortedcontainers are regraded with it.
Human review needed: /apply design, when wanted (checkpoint 8).
```

## Coding sandbox milestone, stage 5b: `/apply`

```text
Date: 2026-10-29
Stage: 5 (terminal workflow, /apply), checkpoint 8
Commit before change: 33d0068
Files changed: src/kiki/apply_command.py (new), terminal.py (/workspace,
        /apply, workspace browser mode), self_knowledge.py,
        tests/test_apply_command.py (new), tests/test_sandbox.py,
        tests/test_run_command.py, README.md, docs
Behavior changed: /workspace picks a folder for this session; /apply FILE
        shows the full diff of the last answer's code block against that
        file and writes on an explicit yes, with a backup and atomic replace.
        Writes outside the workspace, folders, binary files, and files edited
        after the diff was shown are refused. Kiki's self-description says
        she cannot edit files herself.
Tests/evaluations run: pytest 240 passed (17 new). Real-sandbox tests now
        skip with the reason when memory headroom is too low, instead of
        failing; they all ran and passed after unloading Ollama.
Result: the Python coding workflow (write, /run, /apply) is complete.
Known bugs: none found.
Observation: Windows shrank the page file after an earlier spike (commit
        limit 38.8 GB -> 32.9 GB) and grows it again only when commit is
        nearly exhausted. Kiki's headroom checks read the current limit, so
        they are conservative; a fixed page file size would make them, and
        the benchmark guard, behave predictably.
Human review needed: none for this stage. Next capability: the
        generate-test-repair loop (stage 4), measured on the benchmarks.
```

## Coding sandbox milestone: paused

```text
Date: 2026-10-29
Decision: the user paused the coding milestone to avoid a restart for now.
        The loose ends (page-file fix and benchmark resume, HumanEval+ bare
        analysis, receipts, the repair loop, Ollama's memory growth) are
        listed in docs/PROJECT_HANDOFF.md under "Paused on October 29, 2026".
```

## File finding milestone, stage 1: catalog, ranking, `/find`

```text
Date: 2026-10-29
Stage: 1 of docs/FILE_FINDING_HANDOFF.md
Commit before change: d746cc7
Files changed: src/kiki/retrieval.py (schema 5: catalog table, backfill,
        catalog_entries, content_matches), src/kiki/finding.py (new),
        src/kiki/find_evals.py (new), terminal.py (/find), cli.py (kiki find,
        kiki eval-find), self_knowledge.py, tests/test_finding.py (new),
        README.md, docs
Behavior changed: `kiki index` also catalogues every file under the root,
        readable or not, skipping tool folders (.git, node_modules, virtual
        environments, caches) and links. /find ranks whole files by which
        query words their name, title, folder, type, and contents explain,
        weighted by rarity, and shows up to three with a confidence label,
        the reasons, and a copyable path. Missing files are never shown.
Tests/evaluations run: pytest 251 passed (11 new). kiki eval-find:
        development seeds 1-3 (69 cases) and holdout seeds 101-105 (115
        cases): recall@1 1.0, recall@3 1.0; Likely correct 65/65 on holdout,
        Possible 30/40; no Likely on ambiguous or absent questions; 0 deleted,
        dependency-folder, or invalid paths returned; slowest query 0.09 s.
Result: stage 1 works on generated folders and on Kiki's own evals/ and
        docs/ folders (83 files).
Known bugs: the first labelling scored each file alone. On the real
        folders it put a contents-only "Likely" below two "Possible" files
        and labelled three files Likely at once; the generated folders never
        showed this. Fixed: only the first result can be Likely, it must be
        explained mostly by name, title, or folder and lead the next result
        by 0.1, and labels never rise down the list. The holdout seeds were
        rerun after this fix (it came from the real folder, not the holdout).
Known limits: the generator was written alongside the ranker, so the perfect
        scores show the mechanics work, not that real questions will.
        Matching is lexical: "costs" does not find "budget". A file found
        only through its contents is at most Possible. Needs a real personal
        folder to judge.
Decision or proposal: stage 2 (/summarize NUMBER) next.
Human review needed: try /find on a real folder; stage 3 (model tool).
```

## Formats: Word (.docx) and web pages (.html)

```text
Date: 2026-10-29
Stage: Phase 4, first item (requested ahead of file-finding stage 2)
Commit before change: dc5fe2e
Files changed: src/kiki/documents.py (new), extraction.py (dispatch,
        per-format versions, shared line chunker, titles), retrieval.py
        (one location_label for page/paragraph/line), model_client.py,
        terminal.py, tests/test_documents.py (new), README.md, docs
Behavior changed: `kiki index` reads .docx (body text and tables; title
        from the document properties, else a Title or Heading 1 paragraph)
        and .html/.htm (visible text; title from <title>, else the first
        <h1>). Passages cite "paragraphs N-M". Standard library only: no new
        dependency. A .docx body over 64 MB inflated is refused (zip bomb);
        old .doc, password-protected, and damaged files are reported and
        skipped, as unreadable PDFs already were.
Tests/evaluations run: pytest 259 passed (8 new, on .docx files built the
        way Word stores them: runs, tabs, tables, tracked deletions).
        Real files on this PC (40: 37 HTML, 2 Word, 1 .htm; only counts
        printed): 37 read; the 3 with no text are app pages that render
        with JavaScript, and a 3 MB saved page yielded 152 characters for
        the same reason. Largest page: 1.1 MB in 0.63 s.
Result: Word documents and saved web pages are searchable, citable, and
        found by contents and title in /find.
Known limits: headers, footers, footnotes, comments, and text boxes in
        Word are not read; JavaScript-rendered pages have little text; an
        HTML page with no text loses its <title> for /find (it is
        catalogued by name only).
Decision or proposal: file-finding stage 2 (/summarize NUMBER) next.
        Image metadata, OCR, and transcription need review first (new
        dependencies or models).
```
