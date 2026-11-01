# Kiki v2 corpus recovery (2026-11-01)

This directory preserves the personality data recovered from Claude's local
temporary agent workspaces before those directories expire.

## Layout

- `raw/`: earliest recoverable version of each of the 13 fifty-record batch
  slots. One batch (`train_b01b`) contains 44 records.
- `reviewed/`: ten batches for which a fixer produced an output: all three
  development batches and seven training batches.
- `worklogs/`: surviving reviewer/fixer scripts and rendered text from the
  interrupted workflow. These are provenance, not executable instructions.
- `prepared/`: deterministic outputs from `prepare_recovered_v2.py`.

The source files are kept byte-for-byte. Corrections, exclusions, new IDs, and
split decisions happen only in `prepared/`, and every derived record maps back
to a source in `prepared/manifest.json`.

## Prepared splits

- `train_reviewed.jsonl`: 344 records from completed fixer outputs. This is the
  only set eligible for the first v2 training pilot.
- `train_candidates.jsonl`: all 494 recovered training candidates, including
  150 interrupted or partially reviewed records. This is for continued review,
  not training.
- `development.jsonl`: 149 reviewed evaluation records. The original workflow
  called these a holdout, but reviewers and corrections already influenced
  corpus development, so they are honestly labelled development data.
- No final blind holdout exists yet. Create it only after training data and the
  instruction contract are frozen.

One development record duplicated the complete user conversation in a
training candidate (`how many tablespoons in a cup`) and is excluded. All
source batches reused IDs `kiki_v2_0001` through `0050`; prepared IDs are
globally unique.

## Rebuild and validate

```powershell
py -3.12 training/personality/prepare_recovered_v2.py
py -3.12 training/personality/audit_recovered_v2.py
py -3.12 training/personality/validate_v2.py training/personality/recovery/2026-11-01/prepared/train_reviewed.jsonl --corpus
py -3.12 training/personality/validate_v2.py training/personality/recovery/2026-11-01/prepared/development.jsonl --corpus
```

All three prepared datasets passed the corrected structural/content validator
on 2026-11-01. The audit reports zero exact duplicate replies and zero exact
train/development user-conversation overlap.
