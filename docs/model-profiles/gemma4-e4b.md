# Model profile: Gemma 4 E4B

Kiki's official model (owner, 2026-11-01), for her voice and for technical
work. A model profile holds every setting and quirk specific to one model; the
rest of Kiki stays model-agnostic (see the normalization layer in
`../KIKI_BUILD_ORDER.md`, stage 2). Decided in a workshop with the owner on
2026-11-01; not built yet (decide, then build).

## Identity

| | |
| --- | --- |
| Ollama tag | `gemma4:e4b-it-qat` (Q4_0, quantization-aware training) |
| Size | 7.5B parameters stored, about 4.5B effective; image reader 478M |
| Licence | Apache 2.0 (`../research/2026-11-01-gemma-licence.md`) |
| Abilities | text, images, audio, tools, thinking (Ollama's default: thinking **on**) |
| Prompt format | Ollama's built-in Gemma 4 renderer and parser (no editable template) |

## Settings

| Setting | Value | Why |
| --- | --- | --- |
| Context size | **One size for every call**: 8K by default (the user's context preset) | Ollama reloads the model when the size changes: 24 s per reply with two sizes, 1.4 s with one |
| Voice sampling | **Google's defaults**: temperature 1.0, top_k 64, top_p 0.95 | Owner: "for now, to understand its nuances". The model tests ran at 0.7 / 20 / 0.8, so watch how the voice differs |
| Technical sampling | **Temperature 0** (code, documents, web, danger judge, planning) | Every technical score was measured this way (HumanEval+ 90.0% strict, no danger false alarms) |
| Thinking | **Off by default**; opt-in per request (`/think` or a "think harder" setting) | Untested on Gemma. Before building the opt-in, run one benchmark with thinking on. When on, raise the timeouts and the tool-round limit |
| Image reader | **A setting, off by default.** When an image is sent, load the full model (one wait of about 12 s) | It costs about 1.5 GB of memory while loaded; no image tool exists yet |
| Keep loaded | **A setting, default 30 minutes** after the last message | Reloading takes about 12-15 s; loaded, Gemma holds about 6.6 GB of memory and most of the 8 GB of video memory. Unloading can show as idle sleep |
| Prompt-cache cap | **256 MiB** | Bounds llama.cpp's prompt cache at nearly full speed (`../research/2026-11-01-ollama-prompt-cache.md`). Under Ollama, set by the user environment variable `LLAMA_ARG_CACHE_RAM=256`; Kiki's own engine passes `--cache-ram 256` |
| Timeouts | 90 s per reply, 60 s for the danger judge | Enough with thinking off |
| Tool calls | Ollama's native tool format | Behaviour tests 8/8 |

## Checked behaviour

- **Late system messages are kept.** A system message after the first one,
  before or after the user's message, was followed in 3/3 runs, and so was a
  note inside the user's message (control: 0/3). The old rule that later
  system messages are dropped came from v1's custom template, not from Gemma
  or Ollama. Whether v2 uses a real late system message or the note inside
  the user's message is decided in the instruction contract, and v2 data must
  match it.
- **Thinking is off in every Kiki call** (`think=False` in the model client,
  danger judge, and reranker), despite Ollama's default.

## Output clean-up (to build)

- LaTeX: Gemma writes maths as LaTeX; the terminal and chat box don't render
  it, so convert it to plain text.
- Citations: Gemma's citation style for documents differs from Qwen's; parse
  it rather than reject the answer (15 valid citations against Qwen3's 16).
- Repetition: catch looping output at temperature 0 (not yet seen with Gemma).

## Pending

- Thinking-on benchmark (one GPU job) before building the opt-in.
- Voice checks on Google's sampling defaults (the first v2 runs will show the
  difference from 0.7 / 20 / 0.8).
- Recheck the cache cap for the 16K and 32K context presets.
- The owner sets `LLAMA_ARG_CACHE_RAM=256` for development under Ollama.
