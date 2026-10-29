# Persona and tone design

## Goal

Kiki should have a recognizable voice without repeatedly announcing traits,
reciting saved facts, or turning isolated preferences into permanent character
lore. Personality changes phrasing and judgment; it never changes evidence,
tool results, or permissions.

## Open-source patterns reviewed

### Capri Desktop

Capri keeps an editable `personality.md` separate from application-controlled
"machinery" that is appended afterward. It reloads the file without a restart,
backs up edits on reset, and injects a separate `me.md` memory section. Its memory
instruction says to use notes only when they fit and not to recite them. These are
good separation and relevance patterns.

Capri's default persona also contains extensive lore, catchphrases, moods, and
fixed music preferences. That can create strong character consistency, but on a
small local model it can also encourage repetitive callbacks. Kiki deliberately
does not copy that content or design choice.

Sources: [README](https://github.com/lachydotmcg/capri-desktop/blob/main/README.md),
[Brain.cs](https://github.com/lachydotmcg/capri-desktop/blob/main/app/Brain.cs).

### Open WebUI

Open WebUI treats a persona as a model preset that binds a system prompt, tools,
knowledge, and parameters. Its documentation explicitly notes that adherence is
affected by the base model, chat template, conversation, tools, RAG, memory, and
filters—not only the personality prompt. This supports keeping Kiki's layers
visible and independently testable rather than trying to encode everything in a
single character prompt.

Source: [Open WebUI model presets](https://github.com/open-webui/docs/blob/main/docs/features/workspace/models.md).

### Letta

Letta separates a `persona.md`-style self block from user and other memory blocks.
Its guidance emphasizes lean, generalized memory updates and keeping secrets out
of memory. This supports Kiki's separation between persona, explicit user memory,
recent conversation, and operational rules.

Source: [Letta context architecture](https://github.com/letta-ai/letta-code/blob/main/src/agent/prompts/letta.md).

## Kiki's rules

1. Describe stable interaction traits, not favorite objects or fictional history.
2. Do not include few-shot examples containing reusable personal preferences.
3. Keep personality implicit; do not recap it in answers.
4. Treat an in-the-moment opinion as disposable unless explicitly saved.
5. Inject only user-approved durable memory and label it as context, not commands.
6. Tell the model not to recite or mention memory unless it is directly relevant.
7. Append application-controlled evidence, tool, and safety rules independently.
8. Test for both false refusals and irrelevant persona leakage.

## Refusal policy

Kiki should answer benign requests involving analysis, drafting, fiction, coding,
controversial comparison, defensive security education, and general health or
legal education without generic capability disclaimers. When a real capability
is missing, it should state the exact limitation and complete the useful portion
that does not require that capability.

This is separate from tool authorization. Model willingness never grants access
to files, command execution, deletion, purchases, messages, or other external
side effects; those remain code-enforced permission decisions.
