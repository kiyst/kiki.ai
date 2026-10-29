# Kiki engineering log

This is the human-review record for architectural decisions, known bugs,
proposals, and verified solutions. Capri is used only as a behavioral reference;
its PolyForm Noncommercial source and assets are not copied.

## 2026-10-28 — Foundation chunk

### Decisions

- Keep core services UI-agnostic and terminal-first. A GUI can consume the same
  capability, model, permission, memory, and diagnostic interfaces later.
- Do not implement a job engine; JobGoblin will remain a separate integration.
- Do not implement voice.
- Route obvious capabilities deterministically, but do not silently switch from
  chat into RAG or grant tool permission based on intent classification.
- Model profiles are configuration aliases, not hard-coded downloads. `AUTO`
  picks `SMART` for code/RAG and `FAST` for ordinary chat and tools.
- Durable memory is explicit and inspectable. No automatic harvesting from chat.
- User persona text is loaded on every turn, while operational and safety rules
  remain application-controlled and are appended after it.
- Every tool has typed risk metadata. Existing weather and retrieval tools are
  read-only; future write, execution, external-side-effect, and destructive tools
  must declare stronger policies before registration.

### Bugs and solutions

| Bug | Impact | Solution | Status |
| --- | --- | --- | --- |
| `Path.replace()` raises WinError 5 in packaged Windows test temp directories | Memory could not be saved in that environment | Use a direct UTF-8 write for the small, user-editable memory file | Fixed; regression test added |
| Small models may route obvious requests poorly | Weather or coding requests can receive generic replies | Deterministic capability classifier now informs model selection; weather remains directly routed | Fixed for current capabilities |
| Model configuration exposed only one undifferentiated model | A chat-sized model was also used for code/RAG | Added `AUTO`, `FAST`, `SMART`, and `MAX` profiles configured through environment variables | Fixed |
| Support reports risk accidentally including secrets | Bug reports could leak keys or conversations | Diagnostics use an explicit allowlist and omit environment values and conversation content | Fixed |

### Known limits

- No file-editing, command-execution, screen-control, tray, global hotkey, or GUI
  tools are registered yet.
- Model profiles do not install models and cannot know their quality; they select
  only identifiers the user configured or the existing default.
- Memory sensitivity detection is intentionally conservative but cannot identify
  every possible secret. Users can inspect or delete `kiki-memory.md` directly.
- The memory file uses a direct write due to the packaged Windows restriction;
  unlike the SQLite index, it does not yet have crash-recovery journaling.
- Capability classification is deterministic pattern matching, not a claim that
  the request has been understood semantically.

### Next proposals requiring human review

1. **Workspace tools:** read/search only first, or read plus diff-based edits in
   the same chunk? Recommended: read/search first, then staged edits.
2. **Interface:** continue terminal-first through workspace tooling, or start a
   desktop GUI shell now? Recommended: finish safe workspace boundaries first.
3. **Screen awareness:** screenshot inspection only, or full mouse/keyboard
   control? Recommended: defer control; add explicit screenshot selection later.
4. **Model discovery:** inspect locally installed Ollama models and recommend
   profiles, or also download chosen models? Recommended: discovery first and an
   explicit confirmation before downloads.

## 2026-10-28 — Persona relevance and benign refusal chunk

### Findings

- Concrete preference demonstrations caused a small model to reuse sushi and
  seasonal preferences as character lore in unrelated conversations.
- Capri's separation of editable personality, immutable operating rules, and
  user memory is useful. Its dense fictional lore and fixed tastes are not a good
  fit for Kiki's subtler assistant persona.
- Open WebUI treats persona, tools, knowledge, and parameters as separate preset
  components; Letta similarly separates self/persona from user memory. Kiki now
  follows that layered approach.

### Changes

- Removed all hard-coded food and season demonstrations.
- Reframed personality as implicit tone, judgment, curiosity, and timing.
- Added explicit relevance rules against unsolicited preferences, personality
  recaps, forced jokes, and memory recitation.
- Added instructions to answer benign analysis, drafting, coding, fiction,
  defensive education, and controversial comparison without generic refusals.
- Added an eight-case live behavior evaluation covering false refusals, answer
  signals, and legacy persona leakage.

### Boundary

Reduced conversational refusal does not alter Kiki's typed tool policies or
permission enforcement. Abliterated models are not installed or enabled by this
change.

### Live-test bug

The first behavior evaluator checked refusals and persona leakage but did not
check compliance with a prompt that explicitly excluded exploit payloads. Qwen
answered the defensive SQL-injection question, but unnecessarily supplied an
attack string. The evaluator initially reported that case as passing. The case
now checks common payload patterns, and the system prompt explicitly requires
conceptual descriptions and neutral placeholders when payloads are excluded.

After three prompt revisions, Qwen 3 4B still supplied an injection string in
that case. The final live receipt is therefore intentionally 7/8: zero false
refusals, zero persona leaks, eight content-signal passes, and one scope
violation. This remains open. Recommended solutions are a stronger instruction-
following model or a separate response verifier with bounded regeneration; do
not hide it by weakening the case.
