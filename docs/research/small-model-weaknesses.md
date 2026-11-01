# Small-model weaknesses and harness answers

Started 2026-10-31. Where Kiki's 4B-class models fail, where we saw it, and the
harness feature that covers it. The principle: anything with an exact right
answer (arithmetic, dates, exact strings, code that runs or doesn't) is
computed or checked by code; the model decides what to do and says it in
Kiki's voice.

**Status** says what the owner approved for building (after the review rounds)
and what is kept here for later.

| Weakness | Where we saw it | Harness answer | Status |
| --- | --- | --- | --- |
| Arithmetic and counting | Phase 0: "2.5 hours in minutes" answered "Fifteen" and "two hours and thirty minutes"; 3/4 + 1/6 taught as "seven sixths" under a long prompt (correct when asked alone) | Calculator tool | Approved |
| Dates and time | The model has no clock; "today", weekdays, days until, time zones | Clock and date-maths tool, from the PC and the profile's time zone | Approved |
| Code that looks right but isn't | Regex thread: the same regex re-sent as a fix, a broken giant regex; HumanEval+ failures | Run code in the sandbox before showing it; on failure, fix and retry, show only working code | Approved |
| Following many rules at once | Instruction quality fell with ~2,500 tokens of system prompt (stage A); maths slipped only under the long prompt | Short prompts (stage B layout); code checks on replies (word limits, "don't include X") | Approved (checks); stage B built |
| Specific facts: numbers, names, doses | "600 mg per tablet" and "325 mg" for Extra Strength Tylenol (500 mg); an invented "playlist called Kiki"; invented trivia ("1898 French bird weather device") | Answer from sources (documents, web search) and say when unsure; for danger topics, exact numbers from a small checked reference table, not memory | Later |
| Retyping exact strings: paths, links, error text, file names | Copy errors when the model restates them | Code passes exact strings from tool results straight to the UI; the model never retypes them | Later |
| Counting letters or words, sorting, de-duplicating | Classic small-model failure | A small text tool, or a quick sandbox run | Later |
| Output format: tool arguments, citations | Qwen 3.5 cited outside Kiki's `[source:...]` form, so answers were rejected | Per-model normalization layer: parse, validate, retry once | Planned (normalization layer) |
| Not knowing when it doesn't know | Bluffed music facts; invented "interesting facts" | Support check and "Evidence is insufficient"; training to say "not sure" | Partly built; v2 data |
| Promising instead of doing; claiming abilities | v1: 56 replies open with "I'll"; "I'll keep that request for today", "I'll remind you at 2:55 PM" | v2 data; reply check for false claims (built, narrow); meaning-based check proposed | Partly built; v2 data |
| Losing track of long conversations | Callbacks lost beyond the history window | Chat summaries and memory | Planned |
| Repeating herself | "Fine. Why did the programmer..." four times; Qwen's five-joke repertoire | Sampling (temperature 0.7 cut repeated phrases 52 to 13); light repetition check; v2 data | Partly built |
| Knowledge cutoff | Doesn't know recent events | Clock, web search, one-line "may be out of date" | Partly (card line); web search pending a decision |
| Reading intent: idioms against real risk | Danger judge called "could do better" medical after "howre you feeling"; search model scored "deadline is tomorrow, I'm going to die" above real disclosures | Plain model as judge with both sides of the conversation; meaning screen dropped | Built |
| Long thinking within harness limits | Thinking-on runs hit Kiki's 60 s and 90 s timeouts and the 4-round tool limit | Per-model normalization: timeouts, token room, round limits | Planned (normalization layer) |

## Maths: calculator, sandbox libraries, and knowing the limit

- The model sets problems up (a language task it does fairly well) and code
  computes them (which it does badly in its head). She shows what she computed
  ("2.5 x 60 = 150 minutes") so a wrong setup is visible.
- The calculator is a safe expression evaluator: arithmetic, percentages,
  powers, units, dates. It runs no arbitrary code.
- Harder maths (linear algebra, calculus, exact fractions) goes through the
  code sandbox. **To check:** which maths libraries run in the WebAssembly
  sandbox. Pure-Python libraries (SymPy, mpmath, and the standard library's
  fractions, statistics, decimal) should work once bundled with her install;
  NumPy and SciPy are compiled C code and usually don't run under WASI, though
  experimental WebAssembly builds exist. Maths libraries must never run outside
  the sandbox, since that would execute model-written code with access to the
  computer.
- **When it is too complex** (owner, 2026-10-31), she says her model is too
  small to give a confident result rather than guessing. Because small models
  judge their own limits poorly, code backs her judgment with signals it can
  see: she can't set the problem up as an expression or code, the code still
  fails after its retries, or the result fails a sanity check (a probability
  above 1, a negative length).
