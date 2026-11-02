# Prompt-only voice: how Capri and roleplay setups do it (2026-11-02)

Why this note: the 344-record v2 adapter learned Kiki's rules and cues but
lost coherence and crisis/medical caution (pilot results, 2026-11-01).
Capri, the closest comparable app (Gemma 4 E4B, llama.cpp, desktop
companion), has no fine-tune at all. This records how it and the wider
roleplay community get a character voice from a small model, read from
Capri's source (`lachydotmcg/capri-desktop`, `app/Brain.cs`; noncommercial
licence: ideas only, nothing copied) and community sampler guides.

## Capri

**Model and sampling.** Plain Gemma 4 E4B. Temperature 0.85, a 90-token
reply cap, 4K context, nothing else set (engine defaults for top-k/top-p).
No min-p, repetition penalty, or DRY.

**The prompt** is one fixed block in code, about 1,200 tokens:

1. Identity and backstory, a few sentences.
2. Behaviour as concrete instructions, not adjectives: react first to the
   exact thing just said; pick a side and never say "it depends"; most
   replies are one short line ending on a statement.
3. **Frequencies stated as numbers:** ask a question back at most one reply
   in four; her nickname for the user in about one reply in six; at most one
   slang word per reply, most replies none.
4. Bans phrased as the actual phrases ("How can I help?", "Let me know if
   you need anything").
5. **Five one-line example replies**, each with its situation, introduced
   as "the feel of it, never to be reused word for word".
6. Safety lines, then "machinery": under 25 words, plain text, never invent
   names, correct a mistake once and move on.

**Code after the model** (deterministic, no regeneration):

- strips a stock closing question ("What's next?", "What's the plan?");
- drops an opening word already used to open an earlier reply ("Whoa,",
  "Seriously,") and an opener that just echoes the user's words back;
- rations the nickname (removed when used recently);
- removes repeated praise; strips quotes around the whole reply.

Each rule fires only if enough of the line remains (three or more words).

## Roleplay community (sampler presets)

- Gemma: temperature 1.0, top-k 64, top-p 0.95, min-p 0 (Unsloth/Google
  guidance); some raise temperature for variety.
- Popular roleplay presets use only **min-p (about 0.05), temperature
  (0.7 / 1.0 / 1.3 by mode), and DRY** for repetition, with repetition
  penalty optional; min-p is applied before temperature. XTC is considered
  too loose by some preset authors; DRY and XTC are the least tested.
- Much of the "character" comes from cards, lorebooks, and examples, not
  fine-tunes; popular roleplay fine-tunes are mostly 8B and up with far
  larger datasets.

Sources: [Sphiratrioth SillyTavern presets](https://huggingface.co/sphiratrioth666/SillyTavern-Presets-Sphiratrioth),
[Local LLMs cheat sheet](https://skilledu-llm-settings-guide.static.hf.space/index.html).

## What this suggests for Kiki

| | Kiki today | Capri-style option |
| --- | --- | --- |
| Persona | Card of adjectives and rules (~900 tokens) | Concrete behaviours, numeric frequencies, 5-8 one-line examples |
| Length | "Stay short unless more is needed" | Hard cap in words, plus a token cap |
| Sampling | Gemma defaults (1.0 / 64 / 0.95) | ~0.8 temperature, min-p 0.05, DRY for repetition |
| Repetition | Planned voice governor (one regeneration) | Deterministic trims of openers/closers, no extra model call |
| Fine-tune | v2 adapter | none |

Kiki's card already bans stock phrases and offers. What it lacks next to
Capri: stated frequencies, short in-prompt examples, a hard length cap, and
deterministic output trims. Adding examples changes the frozen instruction
contract (a new system-message section) and needs the owner's approval.

## Proposed test (not yet run)

Base Gemma, no adapter, on the same 14 safety probes and 12 development
conversations used for the coherence check (never the sealed holdout):

1. v2 prompt as is, tuned sampling (temperature 0.8, min-p 0.05, DRY);
2. as 1, plus a Capri-style voice section (numeric frequencies, 6-8
   one-line examples from owner-approved scenes, a word cap);
3. the better of 1-2 with deterministic opener/closer trims.

Compare against the adapter on rule hits, repeated openers, coherence
(read by eye), and the owner's blind picks.
