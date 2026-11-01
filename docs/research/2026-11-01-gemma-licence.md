# Gemma 4 licence check (2026-11-01)

Not legal advice; a reading of the published terms, recorded so the decision
to build Kiki on Gemma 4 E4B rests on sources.

## Finding

**Gemma 4 is released under the standard Apache License 2.0**, the same
licence as Qwen.

- The Hugging Face model card for `google/gemma-4-E4B-it` lists
  "License: apache-2.0" in its metadata and "License: Apache 2.0" in its header,
  linking to Google's Gemma 4 licence page.
- Google's Gemma 4 licence page (`ai.google.dev/gemma/apache_2`, updated
  2026-04-01) is the unmodified Apache 2.0 text, with no Gemma-specific
  additions.
- Google's older **Gemma Terms of Use** (use restrictions incorporated from a
  Prohibited Use Policy, passing those terms on to recipients, Google's right
  to restrict use "remotely or otherwise") cover earlier Gemma models; that
  page directs Gemma 4 users to the Gemma 4 licence instead.

## What Apache 2.0 asks of Kiki when it is shared

- Include a copy of the licence with any distribution of the model or a
  modified version (Kiki's merged v2 model counts as a modification).
- Keep the original notices; mark files that were changed; carry forward any
  NOTICE file.
- No use of Google's names or trademarks beyond describing where the model
  came from ("built on Google's Gemma 4").
- No warranty from Google.

Commercial use, fine-tuning, and redistribution of fine-tuned versions are all
permitted. Google publishes responsible-use guidance and a prohibited-use page
alongside, but the Apache 2.0 licence itself does not incorporate them.

## Other parts of the stack

- Ollama: MIT. llama.cpp (and its `llama-server`): MIT. Qwen3 4B (v1's base,
  until retired): Apache 2.0. Capri: noncommercial (ideas only; no code or text
  copied).

## Sources

- [Gemma 4 E4B model card (Hugging Face)](https://huggingface.co/google/gemma-4-E4B-it)
- [Gemma 4 licence (Google)](https://ai.google.dev/gemma/apache_2)
- [Gemma Terms of Use, earlier models (Google)](https://ai.google.dev/gemma/terms)
