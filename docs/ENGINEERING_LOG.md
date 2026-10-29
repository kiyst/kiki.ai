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
