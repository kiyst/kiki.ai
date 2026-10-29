# Kiki personality corpus expansion plan

## Target

Build approximately 1,000 approved SFT conversations before the holdout is
created. The target is a coverage goal, not a quota worth filling with
paraphrases.

Proposed distribution:

| Behavior | Approximate share |
| --- | ---: |
| Ordinary work with little or no humor | 30% |
| Casual personality, references, jabs, and dry refusals | 20% |
| Coding, RAG, files, tools, and accuracy | 20% |
| Multi-turn adaptation and temporary persona changes | 15% |
| Opinions and relationship behavior | 10% |
| High-risk, grief, and explicitly serious situations | 5% |

Greeting and sign-off examples should be mostly plain (for example, “Morning,”
“Goodnight,” or “See ya”). A minority may include a dry or witty remark so
routine conversation does not become a compulsory performance.

At least 20% of the final corpus should be multi-turn. Response lengths should
range from one word to several paragraphs. The expansion must include plain
answers so the adapter does not learn that every reply needs a performance.

## Review process

1. Generate a batch of roughly 100 candidates.
2. Run structural, duplication, phrase-frequency, and capability checks.
3. Present a stratified sample to the user.
4. Apply the user's rules across the entire batch, not only the sampled items.
5. Continue only after the batch's tone is calibrated.
6. Freeze the approved training corpus.
7. Create a novel 100–150 conversation holdout with no prompt paraphrases.

## Training checkpoints

Train comparable pilot adapters at roughly 500 and 1,000 approved examples.
Use the same base model, seed, rank, learning rate, and evaluation set. Choose
the larger corpus only if it improves held-out personality consistency without
increasing repetition or reducing tool, RAG, coding, and factual performance.

More than 1,000 examples may be justified by measured gaps. It should not be
assumed to help merely because the number is larger.

## Progress

- Baseline review corpus: 140 conversations.
- Expansion batch 01: 100 candidates added and structurally validated.
- Current review corpus: 240 conversations, including 30 multi-turn examples.
- Batch 01 status: spot review approved. One greeting example was revised, and
  the resulting mostly-plain greeting rule was propagated across the category.
- Expansion batch 02: 120 candidates added, including 40 multi-turn examples.
- Current review corpus: 360 conversations, including 70 multi-turn examples.
- Batch 02 status: approved after an 86-example spot review. Four examples were
  revised, and the corpus was revalidated after the changes.
- Casual-conversation audit: in progress. The next expansion should increase
  casual and multi-turn casual coverage rather than adding mostly task prompts.
- Expansion batch 03: 140 candidates added to reach the 500-example pilot
  corpus, including 40 casual single-turn and 20 casual multi-turn examples.
- Current review corpus: 500 conversations, including 110 multi-turn examples.
- Batch 03 status: approved after a 20-example spot review. One casual reply
  was revised because it answered a weather-status question instead of the
  user's stated preference question.
