# File finding milestone (Phase 1)

Started October 29, 2026. Goal, from [PROJECT_HANDOFF.md](PROJECT_HANDOFF.md):

> Given a randomized folder containing ordinary documents and opaque files,
> Kiki can answer "I cannot find the file about X" with three ranked file
> candidates, calibrated confidence language, valid copyable paths, and a short
> summary only when content extraction actually succeeded.

Done means held-out file-finding cases show measured recall@k, and deleted or
moved files are never returned as current results.

## Boundaries

- **Read-only.** Finding never opens, moves, renames, edits, or runs a file.
  Opening or revealing a result is Phase 5 and needs its own review.
- **Only folders the user already indexed.** The catalog covers the same roots
  as `kiki index`; it adds no new locations (a human-review checkpoint).
- **Light on memory.** Ranking is SQLite plus Python; no model is loaded to
  find files. Only `summarize` uses the model.
- **Honest about evidence.** A file whose contents could not be read is found
  by name, folder, and dates only, and Kiki says so. No summary is offered for
  it.

## Design

### Catalog

A `catalog` table records every file under each indexed root, including types
Kiki cannot read (images, spreadsheets, archives) and files over the 25 MiB
extraction limit: path, root, name, extension, size, modified time, and
whether its contents are searchable. Developer and tool folders (`.git`,
`node_modules`, `__pycache__`, virtual environments, caches) are skipped. It
is refreshed by `kiki index ROOT`, in the same pass as extraction. Existing
indexes are backfilled from their `files` table and gain the other files on
their next `kiki index`.

### Ranking

Each query word is checked against four fields, strongest first: file name,
document title, folder names (relative to the root, so a folder alias like
"taxes" counts), and extracted contents (the existing full-text index). A
word scores by the strongest field it hits, weighted by how rare it is across
the catalog, so "report" counts less than "Kestrel". Ties break on full-text
relevance and then recency.

### Confidence

Confidence comes from coverage: the share of the query's (rarity-weighted)
words a file explains, and whether its name or title is among them.

| Label | Meaning |
|---|---|
| Likely | Explains nearly all of the query, including in its name, title, or folder, and clearly leads the next candidate |
| Possible | Explains most of the query |
| Weak match | Explains a little; shown only so nothing is hidden |

Each candidate says why it matched ("name: budget; contents: march, rent").
The labels are measured against the evaluation, not assumed.

### Freshness

Before showing a result, Kiki checks the file still exists. Missing files are
never shown; Kiki says how many were skipped and to run `kiki index` again. A
file modified since indexing is shown with a "changed since indexing" note.

### Filters

`/find` accepts `ext:pdf`, `in:FOLDER`, `name:WORD`, `after:DATE`,
`before:DATE` (YYYY, YYYY-MM, YYYY-MM-DD, or `7d`, `4w`, `6m`), `larger:SIZE`,
and `smaller:SIZE` (such as `10MB`).

## Stages

1. **Catalog, ranking, `/find`, `kiki find`.** Clickable paths (where the
   terminal supports them) and a plain copyable path line. The last candidate
   list is kept for follow-ups. Randomized-folder evaluation with development
   and held-out seeds: recall@1 and @3, path correctness, stale rejection,
   and how often each confidence label is right.
2. **`/summarize NUMBER`** for candidates whose contents were extracted, using
   only that file's indexed passages, with citations. Refused, with the
   reason, for opaque files.
3. **A `find_documents` model tool** so "I can't find the file about X" works
   in plain conversation. Read-only, schema-validated, measured on the same
   cases phrased conversationally.

Each stage ends with tests, an engineering-log entry, and a commit.

## Status

- **Stage 1: done** (October 29, 2026). Holdout: recall@1 and @3 of 1.0 on
  115 generated cases, Likely right 65 of 65, no stale or tool-folder
  results. Receipts: `evals/receipts/file-finding/`. The generated folders
  are easier than real ones; a real personal folder is the next test.
