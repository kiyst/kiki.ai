# v2 data and training: process lessons (2026-11-01)

What the first v2 generation run taught, for whoever runs the next round
(Claude, Codex, or the owner). Read with
`docs/KIKI_V2_RECOVERY_AND_REVIEW_HANDOFF.md`.

## Cost

- The multi-agent run (two drafters, two reviewers, and two fixers per 100
  conversations, up to 15 agents at once) used two 5-hour windows and about a
  third of the owner's weekly Claude usage for about 500 conversations.
- Most of the cost was every agent re-reading the full voice reference
  (about 1,100 lines of role-play plus card, sheet, spec, and brief) from
  scratch. Uniform review of low-risk scenes was the second cause.
- **Before any multi-agent job:** state the agent count and a rough token
  estimate and get the owner's go-ahead. Cap concurrency at about five.
  Prefer a short distilled voice digest over the full role-play for agents.

## Scale

- Measure before scaling. The data was scaled toward 1,000+ before anyone
  knew whether 300 would capture most of the gain. Train a pilot, evaluate,
  then add data only for measured failures.
- Draft and review about 10 scenes first; turn the findings into rules;
  only then draft at volume. Batches 1-3 were drafted before the "Lessons
  from review" existed, so the same fixes were paid for repeatedly.

## Review

- Risk-tier it. Deterministic checks for everything; one reviewer for
  flagged or high-risk scenes; a second strong reviewer only for crisis,
  medical, privacy, and destructive actions.
- Sonnet reviewers caught the same classes of problems as Opus reviewers
  (facts, invented details, missing crisis steps) at much lower cost.
- Agreement between two same-family reviewers is not agreement with the
  owner. Use the owner's blind picks as the calibration signal.
- Rules a reviewer flags more than once belong in `validate_v2.py`, not
  only in prose. The crisis "pills at hand, ask whether any were taken"
  rule and "validate the pain, not the wish" were learned three times each
  before becoming validator errors.
- An interrupted fix pass is not a finished one. Batch b05a's fixer died at
  the usage limit and its output was counted as reviewed; two crisis lines
  that called the wish to die understandable survived until a manual check.

## Evaluation honesty

- A set that reviewers and fixers shaped is development data, not a
  holdout. The sealed user-turn holdout (`eval/`) was written before any
  pilot result and must stay untouched by tuning.
- Replaying reference history hides drift; also run free-running
  conversations where her own replies stay in context.

## Tooling

- Never write regexes or code through shell heredocs: `\b` was silently
  turned into a backspace twice. Use the file editor.
- On the RunPod PyTorch image (Ubuntu 24.04), pip refuses system installs
  (PEP 668). Use an isolated venv on the network volume; a
  `--system-site-packages` venv leaked an incompatible torchaudio.
- Put the environment, Hugging Face cache (`HF_HOME`), and artifacts on the
  network volume so a stopped pod loses nothing. Set `PUBLIC_KEY` in the
  pod's environment so SSH starts on its own.
- `run_pilot_v2.sh` runs the whole pipeline with per-step logs, a command
  log, and `.done` markers so it resumes safely after an interruption.

## Contract drift to settle

- `src/kiki/danger.py` (runtime) and the training data's danger notes are
  worded differently. The v2 runtime must send exactly the note text the
  adapter was trained on, or the data must be rebuilt with the new wording.
