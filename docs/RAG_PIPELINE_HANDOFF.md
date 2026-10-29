# Kiki RAG pipeline improvement handoff

Last updated: October 29, 2026

This document supplements `docs/PROJECT_HANDOFF.md`. It describes the next
retrieval-quality milestone and is intended to be passed to another coding
agent before implementation begins.

## Objective

Improve Kiki's grounded document answers without replacing its current
generation or embedding models unnecessarily.

The immediate priority is retrieval quality: the answer model cannot use a
passage that never reaches its context. Changes must therefore be implemented
and measured as separate stages rather than as one large rewrite.

## Current model stack

- Answer and conversational model: `qwen3:4b-instruct`
- Embedding model: `qwen3-embedding:0.6b`
- Current reranking method: pointwise passage grading by the 4B answer model
- Current first-stage candidate pool: approximately 20 passages
- Current final answer context: approximately 5 passages
- Model context budget: approximately 4K tokens

Do not change the answer model or embedding model as part of this milestone.
Changing either would prevent a clean comparison with the existing baseline.

## Existing retrieval behavior

Kiki already has several sound RAG components:

- Qwen-style query instructions are applied to queries but not documents.
- SQLite FTS keyword retrieval and dense semantic retrieval are both used.
- Results are fused with reciprocal-rank fusion.
- Text is split into paragraph-aware overlapping chunks of roughly 1,400
  characters.
- Basic query variants and comparison decomposition exist.
- Named-source coverage is preserved during reranking.
- Answers can abstain when the supplied evidence is insufficient.
- Citation repair is bounded to one retry.

Preserve these behaviors unless an evaluation demonstrates that a specific
component is harmful.

## Baseline to preserve

The existing 14-question held-out retrieval evaluation produced:

| Retrieval mode | Questions with all required evidence in the top five |
| --- | ---: |
| Keyword only | 5/14 |
| Keyword + semantic hybrid | 6/14 |
| Hybrid + current model reranking, earlier measured run | 11/14 |

Before changing code, rerun the relevant evaluation and save a machine-readable
receipt containing:

- Git commit and working-tree status
- Database/corpus identity
- Model names
- Retrieval settings
- Full-evidence-at-k and any-evidence-at-k
- Hit rate at rank 1
- Per-question result
- End-to-end latency
- Reranking latency
- Peak memory or VRAM when it can be measured reliably

If the current numbers differ from the table, retain both results and explain
the environmental or implementation difference. Do not overwrite or silently
replace the historical baseline.

## Proposed implementation sequence

### Stage 1: make retrieval settings configurable

Add configuration for the following values while retaining today's behavior as
the initial default:

- First-stage candidate count
- Final passage count
- Reranker provider and model
- Reranking enabled/disabled
- Maximum reranking batch size
- Maximum answer-context budget

Configuration should work through the existing configuration system and be
visible in diagnostics. Avoid scattering constants across the CLI and
retrieval classes.

Required tests:

- Defaults reproduce the current pipeline.
- Invalid counts and model names fail clearly.
- Reranker failure falls back to fused retrieval order.
- Diagnostics report the active retrieval configuration.

### Stage 2: add a dedicated reranker behind a feature flag

Evaluate `Qwen/Qwen3-Reranker-0.6B` as the preferred dedicated reranker. A
BGE reranker may be implemented as an adapter or comparison target, but it
must not become an undeclared dependency.

Requirements:

- Keep the current 4B pointwise grader available as a compatibility option.
- Do not download a model automatically during ordinary chat or indexing.
- Detect a missing reranker and provide an actionable installation message.
- Use bounded batches and respect local memory constraints.
- Apply explicit timeouts.
- Return structured failures rather than raw library/network exceptions.
- Fall back to fused order if reranking is unavailable or invalid.
- Record which reranker actually produced a result.
- Do not mix reranker scores with retrieval scores as if they shared a scale.

Downloading a new reranker model is a human-review checkpoint. Obtain approval
before the download if it has not already been granted for that exact model.

### Stage 3: run controlled candidate/context experiments

Using the unchanged corpus and held-out questions, compare:

- Candidate pools: 20, 32, and 50
- Final passages: 5 and 8
- Current 4B grader versus the dedicated 0.6B reranker
- Reranking disabled as a control

Run one configuration change at a time. Produce a compact table showing
retrieval quality, answer quality where measured, latency, and memory use.

Do not select a configuration solely because it retrieves more passages. The
chosen default should improve evidence recall without overflowing the answer
context or making interactive use unreasonably slow.

The dedicated reranker must beat or meaningfully match the historical 11/14
full-evidence result before becoming the default. If it does not, retain it as
experimental and document the failure cases.

### Stage 4: improve PDF chunk continuity

The current PDF path is more page-isolated than the text path. Refactor PDF
chunking so a paragraph or short argument can continue across page boundaries
while retaining page-span metadata.

Each resulting passage must preserve:

- Source document identity
- Start and end page
- Stable passage identity
- Extracted text
- Enough metadata to display a useful citation

Do not merge arbitrary pages into large blocks. Use the same approximate
passage-size and overlap policy as text documents, with explicit handling for
headers, footers, blank pages, and extraction failures.

Required fixtures should include:

- A sentence divided across two pages
- A paragraph divided across two pages
- Repeated headers and footers
- A blank page
- A scanned/image-only page with no extractable text
- A malformed or partially readable PDF

### Stage 5: introduce passage-level citations

Answers should cite the specific passage used rather than only the containing
document. A citation record should resolve to:

- Stable passage identifier
- Document path and display name
- Page or line span
- Exact evidence text supplied to the model

Citation validation must reject nonexistent passage identifiers. Keep document
paths out of model-controlled tool arguments where possible; resolve trusted
identifiers in application code.

This stage does not yet require full entailment verification, but the schema
must make later quote checking and sentence-level support checks possible.

### Stage 6: add bounded retrieval recovery

When first-pass evidence is weak, Kiki's application code may perform one
bounded recovery attempt using deterministic query rewriting or decomposition.

Examples:

- Preserve proper names and quoted phrases.
- Split explicit comparisons into one query per subject plus a comparison
  query.
- Expand a broad question into a small number of focused subqueries.
- Search a named document directly when the user identifies one.

Do not make successful retrieval depend entirely on the 4B model deciding to
call a search tool. The orchestrator should own retry limits, timeouts, and
deduplication.

## Later work, not part of this milestone

Do not expand this task into:

- Fine-tuning the embedding, reranking, or answer model
- Replacing Ollama
- A new vector database
- OCR or multimodal indexing
- Whole-drive automatic indexing
- Autonomous file modification
- Desktop GUI or sprite work
- Voice features
- Job-search functionality

These may be separate milestones after the retrieval changes are measured.

## Engineering constraints

- Preserve the terminal-first workflow.
- Keep the index usable if optional reranking dependencies are missing.
- Never silently change embedding identity or vector dimensions in an existing
  index.
- Require a full re-index when embedding identity or preprocessing changes.
- Do not automatically delete or rebuild a user's database.
- Preserve current fallback and structured-error behavior.
- Keep network activity explicit; ordinary RAG queries should remain local.
- Avoid copying code from another project without recording its repository,
  commit, source file, and license.
- Add or update documentation whenever a default or command changes.

## Recommended code shape

Keep the stages behind small interfaces so they can be evaluated independently:

```text
user query
  -> query planner / bounded variants
  -> lexical retriever + semantic retriever
  -> fusion and deduplication
  -> candidate pool
  -> optional dedicated reranker
  -> context-budgeted passage selection
  -> grounded answer generation
  -> passage citation validation
```

The reranker should accept a query and candidate passages and return an ordered
result with structured metadata. It should not own document extraction,
database mutation, answer generation, or UI rendering.

## Completion criteria

This milestone is complete only when:

1. The original evaluation remains reproducible.
2. Retrieval settings and reranker selection are configurable and diagnosable.
3. A dedicated reranker has been evaluated against the existing grader.
4. Candidate-pool and final-context experiments have saved receipts.
5. PDF passages can cross page boundaries without losing page provenance.
6. Citations resolve to specific passages.
7. Failure of the reranker does not prevent a grounded answer using fused
   retrieval order.
8. Existing tests pass and focused new tests cover the changed behavior.
9. Documentation records chosen defaults, rejected alternatives, known bugs,
   and measured tradeoffs.

## Stop and request human review when

- A new model must be downloaded.
- An optional dependency substantially increases installation size or requires
  a different runtime.
- The proposed schema requires destructive database migration or re-indexing.
- The dedicated reranker is slower or less accurate than the current grader.
- The 4K context budget prevents a fair 5-versus-8 passage comparison.
- A change affects default indexed folders, privacy boundaries, or network
  behavior.
- Tests reveal a structural error that invalidates the historical evaluation.
- A licensing question arises from adapting another project's implementation.

## Implementation log format

For each stage, append a short entry to the engineering log containing:

```text
Date:
Stage:
Commit before change:
Files changed:
Behavior changed:
Tests/evaluations run:
Result:
Known bugs:
Decision or proposal:
Human review needed:
```

Do not describe a proposal as implemented until its tests and evaluation have
actually run.

## Reference designs

- Qwen3 Embedding and Reranker:
  <https://github.com/QwenLM/Qwen3-Embedding>
- Zotero RAG, which uses `qwen3-embedding:0.6b`, overlapping chunks, a broad
  first-stage pool, and a dedicated reranker:
  <https://github.com/rhenryliu/zotero-rag>
- Open WebUI retrieval documentation and failure guidance:
  <https://github.com/open-webui/docs/blob/main/docs/troubleshooting/rag.mdx>
- OpenSearch local Ollama RAG tutorial using `qwen3:4b`:
  <https://docs.opensearch.org/latest/tutorials/gen-ai/rag/conversational-search-ollama/>

Use these as architectural references. Verify licenses and exact source code
before adapting implementation details.
