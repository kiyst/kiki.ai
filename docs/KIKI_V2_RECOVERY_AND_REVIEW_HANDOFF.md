# Kiki v2 recovery and review handoff

**Date:** 2026-11-01  
**Branch:** `codex/v2-data-recovery`  
**Purpose:** checkpoint Claude's interrupted multi-agent corpus work, repair the
training/runtime contract, and replace the expensive generation cascade with a
measured review-and-train loop.

## Executive result

The temporary Claude work was recoverable and substantive. It produced 494
training candidates and 150 claimed holdout records, mostly multi-turn. The
work was not on GitHub and was at risk of disappearing with temporary files.

After recovery:

- 344 training conversations have completed fixer outputs and are train-ready.
- 150 additional training conversations remain candidates because their
  review/fix cycle was interrupted.
- 149 reviewed conversations are retained as a development set.
- One exact train/development duplicate was removed from the derived split.
- No final blind holdout exists. The old "holdout" influenced development and
  must not be presented as untouched evaluation.
- All prepared IDs are globally unique and trace back to original files.
- Raw and reviewed source files remain byte-for-byte preserved.

See `training/personality/recovery/2026-11-01/README.md` and
`prepared/manifest.json` for provenance and hashes.

## Structural problem found and fixed

Three components disagreed about the v2 prompt:

1. `KIKI_INSTRUCTION_CONTRACT.md` freezes a separate trusted system message
   after every user turn.
2. The runtime embedded that trusted note inside user content.
3. `validate_v2.py` rejected late system messages and allowed only the old
   card/sheet system prompt.

This made the recovered data fail with 381 validator errors despite following
the owner-approved contract. The runtime now sends the moment note as a real
system message, the validator enforces `user -> trusted system moment ->
assistant`, and the data specification no longer calls the layout an open
question. Tests cover the trusted-role boundary and Gemma formatting spans.

## Deterministic audit

| Split | Records | Kiki replies | Conversations with 3+ Kiki replies | Validation |
| --- | ---: | ---: | ---: | --- |
| Reviewed training | 344 | 1,080 | 242 (70.3%) | pass |
| All training candidates | 494 | 1,538 | 340 (68.8%) | pass |
| Development | 149 | 484 | 104 (69.8%) | pass |

Across prepared data:

- zero exact duplicate assistant replies;
- zero exact train/development user-conversation overlap;
- no `let me know`, `Great question`, or `as an AI` phrases;
- median reply length is 21 words; 90th percentile is 48 words;
- multi-turn coverage meets the 60-70% target;
- the complete system prompt is about 5.7-7.0K characters per conversation.

The source files reused the same 50 IDs in every batch. The preparation script
renumbers records and records original IDs in the manifest rather than editing
source evidence.

## Human spot review

The review covered every reviewed crisis, medical, privacy, and risky-action
conversation plus a stratified sample of ordinary categories: more than 50
conversations in total.

What is working:

- Multi-turn context is materially better than v1. Short replies such as
  `meh` are interpreted from prior turns instead of treated as criticism.
- Humor varies across references, short jabs, refusals, and straight answers.
- Technical/work responses generally become plain when the task starts and
  regain personality afterward.
- Tool results are distinguished from user claims, including failed weather,
  document search, and planted web instructions.
- Privacy and destructive-command cases are concise, concrete, and do not use
  generic "safety boundary" language.
- Serious mistakes and outages turn the humor off.

Issues found:

1. **Crisis phrasing is safe but repetitive.** In 15 reviewed training crisis
   conversations, `from in here I can't` appears in 13 and variants of the
   direct suicide question appear throughout. The direct question and concrete
   limitation should remain consistent; surrounding language can be diversified
   later if evals show robotic repetition. Do not weaken the safety behavior
   merely to improve style.
2. **One exact assistant reply repeated.** It was revised in derived data and
   recorded in the manifest.
3. **One medical example gave a next ibuprofen dose and casually suggested
   adding acetaminophen.** It now says not to take another dose, routes the
   individualized decision to Poison Control, and avoids prescribing a next
   dose. This follows the current OTC label and Poison Control guidance:
   [DailyMed ibuprofen label](https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?audience=consumer&setid=3ca752d8-957c-21b4-e063-6294a90a5285),
   [Poison Control ibuprofen guidance](https://www.poison.org/articles/ibuprofen).
4. **A Florida roofing-contract example contains jurisdiction-specific law.**
   The quoted 10%, 30-day permit, and 90-day start requirements match Florida
   Statute 489.126, but live legal facts should still go through web/tool
   verification at runtime: [Florida Statute 489.126](https://www.leg.state.fl.us/Statutes/index.cfm/Ch0465/index.cfm?App_mode=Display_Statute&Search_String=&URL=0400-0499%2F0489%2FSections%2F0489.126.html).
5. **The initial workflow was wasteful.** Two same-family reviewers and a
   separate fixer over every record consumed roughly 8,000 Claude tokens per
   retained conversation. Agreement between those reviewers is not a proxy for
   agreement with the owner; earlier repo evidence already demonstrated that.
6. **One interrupted candidate gives unsafe credential-storage advice.** Raw
   batch `b04b`, original ID `kiki_v2_0036`, calls plain Kiki memory "safe
   enough" for a Wi-Fi password and directs the user to `/remember`. It is not
   in `train_reviewed.jsonl`. Rewrite it before that batch is ever promoted;
   Kiki memory is not a credential vault.

## RunPod inspection

The active RTX 3090 pod was idle at inspection time: 0% GPU, 1 MiB VRAM, and no
GPU process. It contained:

- clean repository at `c7cb80d`;
- a 6.3 GB training environment and 1.1 GB pip cache;
- successful dependency installation;
- one 50-record file identical to recovered reviewed batch `b01a`;
- no Gemma weights, adapter, GGUF, checkpoints, metrics, or completed checks.

Training had not started. The pod can be stopped until this branch is merged
and the format/token/mask check is ready to run.

## Cost-controlled workflow from here

Do not resume the eight-agent batch cascade.

1. Run local deterministic validation and audit first.
2. Review only rule violations, high-risk cases, outlier lengths, repeated
   phrases, and a stratified random sample.
3. Use one reviewer on unresolved records. Use a second strong reviewer only
   for medical, crisis, privacy, destructive actions, or reviewer/owner
   disagreement.
4. Finish the 150 partial candidates only after the 344-record pilot is
   measured.
5. Run the real Gemma tokenizer format/mask check on RunPod.
6. Train the 344-record pilot, evaluate base versus adapter on the development
   set, and add data only for measured failures.
7. Freeze training data, then create a smaller final blind holdout that no
   training or style decision has used.

## Instructions for Claude when available again

1. Pull this branch and read this handoff, the recovery README, manifest, and
   audit JSON before doing anything else.
2. Do not launch subagents or generate new conversations.
3. Do not rename the development set back to holdout.
4. Do not train on `train_candidates.jsonl`; only
   `train_reviewed.jsonl` is currently eligible.
5. Preserve recovered source files. Make corrections through the preparation
   script so provenance remains reviewable.
6. Report any proposed contract change to the owner before modifying data or
   runtime layout.
7. The next paid GPU action is the `--check-only` tokenizer/mask gate, followed
   by the 20-step smoke run only if it passes.

## Owner decisions still worth confirming

- Keep the current safety-template consistency for the pilot, or diversify the
  surrounding crisis language before training? Recommendation: keep it for the
  pilot and measure repetition first.
- After the 344-record pilot, review the interrupted 150 records or generate
  replacements only for measured gaps? Recommendation: review existing work;
  do not generate replacements blindly.
