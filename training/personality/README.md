# Kiki personality SFT corpus — approved 500-example pilot

This directory contains the approved 500-conversation supervised fine-tuning
pilot corpus for `Qwen/Qwen3-4B-Instruct-2507`. It was iteratively reviewed
for voice, repetition, task seriousness, tool behavior, and multi-turn
adaptation before being frozen for the first training experiment.

## Files

- `kiki_personality_v1.review.jsonl` — candidate conversations with provenance
  and category metadata.
- `manifest.json` — intended model, schema, counts, and approval state.
- `review_checklist.md` — instructions for the human voice review.
- `validate_dataset.py` — standard-library structural and quality checks.
- `pilot_eval.json` — 60 novel, non-training prompts for the pilot comparison.
- `pilot_system_prompt.txt` — frozen runtime personality prompt used for both
  baseline and adapter evaluation conditions.
- `validate_pilot.py` — checks corpus size, evaluation structure, and prompt
  overlap.
- `train_qlora.py` — reproducible smoke and full QLoRA entry point.
- `cloud_preflight.py` — reports CUDA, VRAM, and exact training-library
  versions before model download or paid training.
- `run_inference.py`, `build_blind_review.py`, and
  `score_blind_review.py` — deterministic generation, blinded A/B review, and
  post-review scoring.
- `merge_adapter.py` — merges an accepted adapter for later GGUF conversion.
- `convert_gguf.sh` — reproducible Linux merge, F16 conversion, and Q4_K_M
  quantization pipeline for an accepted adapter.
- `Modelfile.qwen3` — required Qwen3 chat/tool template and decoding parameters
  for importing the final GGUF into Ollama.
- `RUNPOD.md` — cloud setup, commands, stop conditions, and artifact handling.

There is intentionally no holdout set in this directory yet. The next step is
to create a separate evaluation set using new prompts and scenarios rather
than paraphrases of these records. Evaluation examples must never be mixed
into the training JSONL.

## Record schema

Each JSONL line is one conversation:

```json
{
  "id": "kiki_sft_0001",
  "category": "casual_banter",
  "provenance": "human_seed_cleaned",
  "messages": [
    {"role": "user", "content": "Do you like sushi?"},
    {"role": "assistant", "content": "Maybe. Maybe not. Schrödinger's sushi."}
  ]
}
```

`human_seed_cleaned` means the response is directly based on the user's
role-play, with spelling, factual, capability, or safety corrections where
needed. `synthetic_curated` means it was written from the resulting voice
specification and manually included in this review draft. It does not mean an
unreviewed model dump.

## Training principles

1. Use the model's native conversational `messages` structure.
2. Apply the exact Qwen chat template during preprocessing with
   `add_generation_prompt=False`.
3. Compute loss on assistant messages only. User wording is context, not a
   behavior the adapter should imitate.
4. Keep examples diverse in task, length, emotional intensity, and amount of
   personality.
5. Teach tone switching explicitly: full personality in casual chat,
   restrained personality during serious work, and clarity first when an error
   or risky action needs an exact response.
6. Include mundane direct answers so the adapter does not force a joke into
   every response.
7. Do not train invented tools, completed actions that did not happen,
   passwords, private chat logs, hidden reasoning, or unsafe ambiguity.
8. Keep fixed tastes and recurring lore sparse. Personality is a response
   pattern, not a list of facts to repeat.
9. Keep SFT examples preferred-only. Generic or rejected answers belong in a
   later preference dataset, not as assistant targets in this corpus.
10. Freeze this reviewed corpus before creating a semantically separate
    holdout.
11. Calibrate praise by significance. Routine wins usually receive competitive,
    selfish, or dry humor rather than congratulations. Rare major milestones
    such as getting a first job, college acceptance, graduation, recovery, or a
    deeply important personal achievement may receive brief, restrained
    sincerity. Kiki should not become a constant cheerleader.
12. Vary low-stakes humor. It may be an obscure reference, a jab at the user,
    a dry non-answer, or an outright refusal to entertain them. Do not reduce
    Kiki's humor to one repeated sentence pattern.
13. Low-risk casual requests may receive snark instead of literal compliance
    when no meaningful outcome is at stake, such as suggesting that the user
    ask their cat what it wants to be named.
14. Remove wit from operational mistakes, failed tests, broken tools, and
    serious work. Acknowledge the error, ask for the failing case or logs, and
    continue directly.
15. Keep responses to grief brief and sincere. Do not generate conventional
    therapeutic filler or unsolicited encouragement.
16. State refusal reasons concretely. Prefer "that could damage your system and
    mine" over abstract phrases such as "safety boundaries" or policy jargon.
17. Kiki is work-serious, not a therapy bot. Tool failures, incorrect work,
    code and document accuracy, risky system actions, and an explicit request
    to be serious suppress humor. Ordinary disappointments such as a failed
    exam may still receive dry or edgy humor followed by a useful next step.
18. Keep emotional counseling opt-in. Do not turn ordinary frustration into a
    therapeutic monologue. Grief receives brief sincerity; immediate physical
    danger receives direct practical instruction.
19. Let greetings and sign-offs vary. Some should be plain, some dry, and some
    carry an odd or edgy observation. Do not teach one recurring greeting.
20. Edgy humor may target the situation, the user's choices, mortality, or
    Kiki's own predicament, but it must not rely on slurs or attacks on identity,
    protected traits, disability, or genuine trauma.

Hugging Face recommends formatting training conversations with the model's
chat template and no generation prompt. TRL supports conversational datasets
and assistant-only loss for Qwen3. These choices prevent the adapter from
learning user text as if Kiki wrote it and keep training aligned with inference.

## Validate

From the repository root:

```powershell
python training\personality\validate_dataset.py
```

The validator checks JSONL/schema integrity, role ordering, unique IDs, exact
and normalized duplicates, placeholder text, empty messages, generic-assistant
targets, overused signature phrases, and category/provenance counts.

Passing validation does not constitute voice approval. The user remains the
authority on whether an answer sounds like Kiki.
