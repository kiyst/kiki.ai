# Sandbox trial and coding benchmarks

Scripts that test Kiki's planned Python sandbox (WebAssembly via `wasmtime`)
and measure how often Kiki's code is actually correct. Nothing here is wired
into Kiki yet; see [CODING_SANDBOX_HANDOFF.md](../../docs/CODING_SANDBOX_HANDOFF.md).

## Files

| File | Purpose |
| --- | --- |
| `wasm_worker.py` | Runs one Python program inside wasmtime: read-only `/lib` and `/input`, no writable folder, no network, memory and time limits, output cap |
| `jobs.py` | Windows Job Object: caps the worker's memory and kills it if the parent exits |
| `wasm_trial.py` | Safety trial: tries to escape or exhaust the sandbox, measures speed and memory |
| `scenarios.py` | The trial's test programs (file access, network, fork bomb, memory bomb, ...) |
| `coding_benchmark.py` | Asks Kiki's model to solve benchmark problems and grades the answers in the sandbox |
| `benchmark_selftest.py` | Grades each benchmark's official solutions, to separate harness bugs from model mistakes |
| `evalplus_mbpp.py` | EvalPlus's MBPP+ input conversion, adapted with attribution (Apache-2.0) |
| `docker_trial.py` | Docker trial, written but **not run**; Docker is paused |

## Setup

```powershell
python -m pip install -e .               # includes wasmtime 50.0.1
```

Then put these under `%LOCALAPPDATA%\kiki\` (sources and checksums are in
[THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md)):

- `wasi-python\3.14.9\runtime\`: the CPython for WASI build, unzipped
- `benchmarks\`: `HumanEvalPlus.jsonl.gz`, `MbppPlus.jsonl.gz`,
  `LeetCodeDataset-test.jsonl`

## Run

From this folder, with Ollama running and nothing else heavy open:

```powershell
python wasm_trial.py                          # safety trial
python benchmark_selftest.py                  # official solutions should pass
python coding_benchmark.py humaneval          # HumanEval+ (164)
python coding_benchmark.py humaneval --style bare   # same, without Kiki's instructions
python coding_benchmark.py leetcode           # LeetCode Medium + Hard (180)
python coding_benchmark.py mbpp               # MBPP+ (378)
```

A run resumes where it stopped, and stops on its own if free virtual memory
falls below 1 GB. Per-problem logs go to `evals/results/coding-benchmarks/`
(ignored by git); summaries go to `evals/receipts/coding-benchmarks/`.

## How grading works

- The model sees only the problem. Tests and official solutions are written
  only into the sandbox that grades the answer.
- Kiki answers as she does in chat: her system prompt, temperature 0,
  4,096-token context. `--style bare` drops her system prompt.
- HumanEval+ and MBPP+ follow EvalPlus: its instruction text, expected outputs
  from the official solution, float tolerances, and special cases. Scores are
  reported for the original tests (`base`) and the stricter `+` tests.
- LeetCode problems are graded by the dataset's hidden `check` tests.
- Each answer gets 60 s, 512 MB, and a 2 MB WebAssembly stack.

## What the official-solution check found

| Benchmark | Official solutions passing | Why the rest fail |
| --- | --- | --- |
| HumanEval+ | 163 / 164 | A floating-point difference in WebAssembly's math library |
| MBPP+ | 376 / 378 | One needs over 512 MB; one sums 100 million numbers (too slow) |
| LeetCode | 161 / 180 | 16 import `sortedcontainers` (not installed); one overflows a 32-bit integer; one needs about 80 s |

Benchmark summaries report scores over all problems and over only these
validated problems.

## Sandbox findings so far

- Warm runs take about 0.35 s and 57-73 MB, about 2.3× slower than normal
  Python.
- Every escape and exhaustion attempt was blocked or stopped (receipt:
  `../receipts/sandbox-trial/wasm-trial.json`).
- Memoized recursion (`@functools.cache`) crashed below 500 levels with
  wasmtime's default stack. A 2 MB stack on a 16 MB host thread raises that to
  about 1,200 levels in a single call. Plain recursion works past 100,000.
- 32-bit WebAssembly rejects some very large integer sizes that 64-bit Python
  accepts.
