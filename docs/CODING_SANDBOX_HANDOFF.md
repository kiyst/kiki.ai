# Kiki coding sandbox handoff

Last updated: October 29, 2026

This document specifies a future milestone: a sandboxed environment in which
Kiki can run code she writes, test it, and repair it. It is written for the
coding agent that will implement it and for the human reviewer who approves
each checkpoint. **Nothing in this document is implemented yet.**

It supplements [PROJECT_HANDOFF.md](PROJECT_HANDOFF.md). The idea was raised
earlier as suggestion 5 in [DEVELOPMENT_NOTES.md](DEVELOPMENT_NOTES.md) ("keep
permissions in code ... require your confirmation and a chosen workspace") and
in [ENGINEERING_LOG.md](ENGINEERING_LOG.md) ("future write, execution,
external-side-effect, and destructive tools must declare stronger policies
before registration").

## Approval status

Approved by the user on October 29, 2026, as a separate milestone, with:

- Execution triggered by benchmarks automatically, and in chat only by `/run`
  with an explicit confirmation.
- **WebAssembly as the isolation boundary** (revised the same day). The first
  draft used Docker. The user chose WebAssembly instead because Docker
  Desktop's VM costs 1-2 GB of RAM on a machine that had just run out of
  memory, while WebAssembly needs about 25 MB of disk and no background
  service. The user accepted `wasmtime` as a required Kiki dependency. Docker
  remains a possible later backend ([Deferred: Docker backend](#deferred-docker-backend)).

Approval of the milestone is not approval of its checkpoints. Every item under
[Human-review checkpoints](#human-review-checkpoints) still needs a yes before
it happens.

## Objective

Raise the share of Kiki's code that actually works, measured by hidden tests,
without giving generated code any path to the user's files, network, or the
stability of the host.

Success means:

1. Generated code runs only inside a disposable WebAssembly sandbox with no
   file, network, or process access beyond what is granted per run.
2. A benchmark with hidden tests measures pass rate honestly.
3. A bounded generate-test-repair loop measurably raises that pass rate.
4. In chat, `/run` executes a temporary copy after confirmation, and any
   change to real files is shown as a diff and applied only on approval.

## Non-goals

- Running generated code on the host outside the sandbox. There is no
  fallback.
- Network access from generated code, including installing packages.
- Third-party packages (numpy and so on). First version: Python standard
  library, minus what WASI lacks (threads, subprocesses, sockets).
- Languages other than Python in the first version.
- GPU access, long-lived sandboxes, background services, or notebooks.
- Autonomous edits, commits, or file moves. Kiki proposes; the user approves.
- Replacing the answer model inside this milestone. That is a separately
  measured, separately approved step (stage 6).

## Current state

- **Coding help exists, execution does not.** `capabilities.py` routes coding
  prompts to the `SMART` profile (currently `qwen3:4b-instruct`, the same as
  every profile). `CHAT_SYSTEM_PROMPT` asks for approach, complexity, edge
  cases, and code, and forbids leaving a known-broken draft in the answer.
- **The coding evaluation is static.** `kiki eval-chat` has 10 LeetCode-style
  problems in `evals/coding_cases.json`. It checks for refusals, required
  algorithm keywords, and whether Python code blocks parse (`ast`). It never
  runs the code, so correctness is unknown.
- **Permissions already model execution.** `permissions.py` defines
  `RiskLevel.EXECUTE` and `RiskLevel.LOCAL_WRITE`, both requiring
  confirmation, and `ToolRegistry.call` refuses unapproved calls. No tool uses
  them yet.
- **Machine:** Windows 11 Home (no Windows Sandbox), Ryzen 5 3600 (12
  threads), 16 GB RAM, GTX 1080 8 GB. Docker 29.7.2 is installed but not
  needed by this plan.
- **Memory is the binding constraint.** On October 29 the PC ran out of virtual
  memory and had to be restarted (incident in the engineering log). Fusion
  360 and Ollama alone triggered low-memory warnings. Any design that adds
  memory pressure must cap it.

## Why WebAssembly

| Option | Isolation | Memory cost | Start per run | Decision |
| --- | --- | --- | --- | --- |
| Host subprocess with limits | None for files or network | Tiny | Instant | Rejected: not a boundary |
| Windows Sandbox | VM | ~1 GB | Slow | Unavailable on Windows 11 Home |
| Docker Desktop (WSL 2) | Container in a VM | 1-2 GB VM while running | ~1-2 s | Deferred: heavier, needs Docker Desktop running |
| **wasmtime + CPython for WASI** | Capability-based: no files, network, or processes unless granted | Tens of MB per run (to be measured) | Sub-second once compiled (to be measured) | **Chosen** |
| RestrictedPython / AST filtering | Language-level only, bypassable | Tiny | Instant | Rejected: not a boundary |

Dependency facts checked on October 29, 2026:

- `wasmtime` on PyPI: version 50.0.1, Apache-2.0 WITH LLVM-exception, 8.0 MB
  `win_amd64` wheel, no runtime dependencies.
- CPython for WASI: `brettcannon/cpython-wasi-build` (maintained by a CPython
  core developer), latest `v3.15.2` (October 27, 2026), asset
  `python-3.15.2-wasi_sdk-33.zip`, 15.5 MB, PSF license. The exact version is
  chosen at checkpoint 2. Prefer a release whose minor version Kiki's own
  tests already cover.

## Architecture

```text
model answer (text)
  -> code extractor        pulls fenced Python blocks; model output is data only
  -> staging               disposable host temp dir: main.py (+ visible tests)
  -> SandboxRunner         starts a worker process with a fixed argv (no shell)
       worker: wasmtime instance of python.wasm
               preopens: /lib (stdlib, read-only), /input (staging copy, read-only)
               no writable directory, no sockets, no env beyond an allowlist
               memory limit, epoch deadline, output cap
       worker process: Windows Job Object (memory cap, kill-on-close)
  -> RunResult             exit code, bounded stdout/stderr, timings, limit flags
  -> cleanup               worker ended, staging dir deleted, always

benchmark:  RunResult(hidden tests) -> score only; never shown to the model
repair:     RunResult(visible tests) -> short error summary -> model (max 2 rounds)
chat /run:  confirm -> temporary copy -> RunResult shown to user
edits:      proposed change -> unified diff -> explicit approval -> write to
            the selected workspace (LOCAL_WRITE), never via the sandbox
```

### Components (proposed module `src/kiki/sandbox/`)

| Component | Responsibility | Must not |
| --- | --- | --- |
| `runtimes.py` | Allowlist: runtime name -> pinned runtime version, sha256, file layout, fixed guest argv | Accept a runtime, path, or argv from model or user text |
| `staging.py` | Create a per-run temp dir, write files from memory, enforce size and count limits, delete it | Copy or link from the user's workspace; follow symlinks |
| `wasi.py` | Configure the wasmtime engine and store: preopens, memory limit, epoch deadline, stdout/stderr capture; cache the compiled module | Grant a writable directory, sockets, inherited env, or host paths beyond `/lib` and `/input` |
| `worker.py` | Entry point of the child process; runs one sandbox instance and writes a JSON result | Read anything from the parent except the fixed run spec |
| `runner.py` | Start the worker with a fixed argv (`shell=False`), place it in a Job Object, enforce the backstop timeout and output caps, clean up | Interpolate any string into a command line |
| `preflight.py` | Fail-closed checks: `wasmtime` importable at the pinned version, runtime present with the pinned sha256, compiled cache valid | Download the runtime or install packages by itself |
| `benchmark.py` | Load problems; keep hidden tests in a separate store; grade in the sandbox; write receipts | Put hidden test text in any prompt, log shown to the model, or repair message |
| `repair.py` | Generate -> run visible tests -> summarize failure -> regenerate, at most 2 repairs | See hidden tests or their results beyond the final score |
| `edits.py` | Turn a proposed file change into a unified diff; apply only on explicit approval to a user-selected workspace | Write anywhere else; apply anything produced inside the sandbox |

### Execution is not editing

- `/run` executes a **temporary copy** only. The staging directory is created
  fresh for that run from text held in memory (the code block or files the
  user names), and deleted afterwards.
- The original workspace is **never preopened** into the sandbox, writable or
  otherwise. If the user asks to run a file from their project, its contents
  are copied into staging; the sandbox sees only the copy, read-only at
  `/input`.
- The sandbox has no writable directory, so nothing it produces can be written
  back to the host. Its only outputs are stdout, stderr, and the exit code.
- A persistent change to the user's files is a separate action: Kiki shows a
  unified diff, the user approves it explicitly, and application code writes it
  under the `LOCAL_WRITE` policy to a workspace the user selected.
- Execution is never triggered by the model. The model's only output is text;
  code runs because the benchmark harness or the user's `/run` said so. A turn
  in which the model read retrieved document text cannot trigger execution.

## Sandbox specification

Requirements:

- **Disposable workspace per run:** a fresh staging dir, a fresh wasmtime
  store and instance, and a fresh worker process for every run.
- **Read-only grants only:** the only preopened directories are the pinned
  standard library (`/lib`) and the staging copy (`/input`), both read-only
  (wasmtime directory and file permissions set to read). No writable
  directory exists; `-B` and `PYTHONDONTWRITEBYTECODE=1` keep Python from
  trying to write bytecode.
- **No network:** CPython for WASI (preview 1) has no socket support, and no
  socket capability is granted.
- **No processes:** WASI has no `fork`, `exec`, or `subprocess`; fork bombs
  and child processes are impossible inside the guest.
- **No ambient host access:** no inherited environment (fixed allowlist:
  `PYTHONDONTWRITEBYTECODE`, `PYTHONUNBUFFERED`, `PYTHONHOME=/lib`,
  `PYTHONSAFEPATH=1`), no inherited stdin, fixed guest argv.
- **Pinned runtime:** the CPython WASI build is referenced by version and
  sha256 in `runtimes.py`, stored under `%LOCALAPPDATA%\kiki\wasi-python\<version>`,
  and verified by preflight. The `wasmtime` package is pinned to an exact
  version in `pyproject.toml`.
- **Compiled-module cache:** `python.wasm` is compiled once and serialized
  under `%LOCALAPPDATA%\kiki\wasi-python\<version>\cache`, keyed by the
  wasmtime version and the runtime sha256. Deserializing compiled code skips
  validation, so the cache is trusted only if its own recorded sha256 matches;
  otherwise it is rebuilt.
- **Structured invocation:** the worker is started with
  `subprocess.Popen([sys.executable, "-I", "-m", "kiki.sandbox.worker", <spec file>], shell=False)`.
  Model or user text can only become file contents in staging, never an
  argument, path, preopen, or environment variable.
- **Strict runtime allowlist:** one runtime, `python-wasi`, with a fixed
  launcher. Unknown runtimes are rejected before a worker starts.
- **Cleanup after every run:** worker ended and staging dir removed on
  success, failure, timeout, and exceptions. The Job Object uses
  kill-on-close, so a worker cannot outlive Kiki. A startup sweep removes
  leftover staging dirs (named `kiki-run-*`).
- **Fail closed:** if `wasmtime` is missing or the wrong version, the runtime
  is missing or its sha256 differs, or the Job Object cannot be created, the
  run is refused with an actionable message (`kiki sandbox setup`). There is
  never a host-execution fallback. Chat, search, and RAG keep working; only
  execution is unavailable.

The launcher (`kiki_launcher.py`, written by Kiki, not the model) is placed in
staging. It caps `sys.stdout` and `sys.stderr`, then runs the program or the
test module with `runpy`/`unittest` and fixed arguments.

## Resource limits

| Limit | Value | Enforced by | Why |
| --- | --- | --- | --- |
| Wall time | 10 s run, 30 s benchmark case | wasmtime epoch deadline (timer thread); parent kills the worker 2 s later as a backstop | Infinite loops |
| CPU | 1 core | WASI Python is single-threaded; one worker at a time | Keep Ollama and the desktop responsive |
| Guest memory | 256 MiB | `Store.set_limits(memory_size=...)` | Memory bombs; the host is tight |
| Worker process memory | 768 MiB (guest + compiled code + wasmtime) | Job Object process memory limit | Backstop if the engine itself grows |
| Processes | 0 in the guest | WASI has no process creation | Fork bombs |
| Disk writes | 0 bytes | No writable preopen | Disk filling |
| Output | 64 KiB stdout + 16 KiB stderr kept; worker killed after 1 MiB | Launcher cap, plus the parent watching the capture file size | Flooding the terminal or model context |
| Recursion and stack | wasmtime stack limit; Python recursion limit | Trap reported as `crashed` | Deep recursion |
| Input staging | 2 MiB total, 50 files | `staging.py` | Bounded copies |
| Concurrency | 1 run at a time | Host lock | One heavy job at a time |

All numbers are starting values; the stage-1 trial run measures real startup
time and memory, and any change goes through checkpoint 8.

Each limit hit is reported (`timed_out`, `memory_exceeded`,
`output_truncated`, `crashed`, and so on) instead of looking like an ordinary
failure.

## Threat model

**Assets:** the user's files and credentials; network access and anything
reachable from it; host stability (RAM, disk, responsiveness); Kiki's own
index, memory, and persona files; the integrity of benchmark results.

**Untrusted inputs:** model-generated code (buggy or adversarial); prompt
injection from retrieved documents or pasted text that steers the model's
code; user-supplied code run via `/run`.

| Threat | Example | Mitigation | Residual risk |
| --- | --- | --- | --- |
| Read or alter user files | `open("C:/Users/...")`, `shutil.rmtree` | Only `/lib` and `/input` exist in the guest, both read-only; nothing written back | None known within wasmtime's guarantees |
| Exfiltration or downloads | HTTP requests, DNS, `pip install` | No sockets in WASI preview 1; none granted | Covert channels via output text (bounded by output caps) |
| Sandbox escape | Exploiting a wasmtime or Cranelift bug | Pinned, current wasmtime; small attack surface; worker is a separate process in a Job Object | An escape runs with the user's rights in the worker process. This boundary is one layer, where Docker on Windows is two (container plus VM). Accepted for stdlib-only code; revisit before adding packages or other languages |
| Injection into the invocation | Model text becoming an argument or path | Worker argv and run spec built from typed fields; text only becomes file contents | Bugs in the spec builder (tested) |
| Resource exhaustion | Memory bomb, infinite loop, output flood, deep recursion | Limits table; one run at a time | Brief memory spike up to the Job Object cap |
| Persistence | Background processes, scheduled tasks | No processes or writable files in the guest; Job Object kill-on-close; startup sweep | None known |
| Supply chain | Tampered runtime or package | Pinned `wasmtime` version; runtime sha256 verified; compiled cache verified | Trust in PyPI and the runtime publisher at review time |
| Hidden-test leakage | Tests copied into prompts or repair feedback | Separate store; only the grader reads them; canary test | Model memorization of public problems (use original variants) |
| Benchmark gaming | Code that reads test files or prints "OK" | Hidden tests staged only for grading; grader checks results structurally (results file written by the launcher, not by stdout text) | Weak test design; review the tests |
| Unintended execution | Model or document text triggering a run | Execution only from the benchmark harness or `/run` + confirmation; tools with `EXECUTE` risk require approval | User approving without reading (show the code first) |
| Unapproved edits | Writing results back to the workspace | Edits only via diff + explicit approval under `LOCAL_WRITE` | User approving a bad diff |

## Hidden benchmark tests

- Each problem has a prompt, **visible** examples (may be shown to the model),
  and **hidden** tests (never shown).
- Hidden tests live in their own file tree (for example
  `evals/coding_hidden/`), are loaded only by the grader, and are copied only
  into the grading run's staging dir.
- The model never receives hidden test text, hidden test names, or hidden
  failure output. The repair loop sees only visible-test results; the final
  hidden-test score goes only into the receipt.
- A canary string in every hidden test file, plus a test that captures every
  model request (fake client) and asserts the canary never appears.
- Problems are split into development and holdout, as in the retrieval work;
  defaults and prompts are tuned on development only.
- Problems use only standard-library modules that work under WASI (the
  stage-1 trial records which do).

## Staged implementation

Each stage ends with focused tests, a receipt where a model is involved, an
engineering-log entry in the existing format, and a separate commit.

### Stage 0: baseline and benchmark design (no execution)

- Re-run `kiki eval-chat` and save a receipt.
- Write about 40 original Python problems (10 easy, 20 medium, 10 hard) with
  visible examples and hidden tests; split 15 development / 25 holdout.
  Original wording and variants reduce memorization.
- Review the tests themselves (do they test the stated behavior?).

### Stage 1: dependency, runtime, trial run, preflight

- Add `wasmtime` (exact version) to `pyproject.toml` (checkpoint 1).
- `kiki sandbox setup`: download the pinned CPython WASI build, verify its
  sha256, unpack it, compile and cache the module (checkpoint 2).
- `kiki sandbox doctor`: package version, runtime sha256, cache, Job Object.
- Trial run, recorded in the log: cold and warm startup, worker peak memory,
  hello world, and a first check that the memory limit, the epoch deadline,
  and read-only grants actually hold. Record which stdlib modules import.
- **Go/no-go:** if warm startup exceeds 2 s, worker memory exceeds 768 MiB, or
  any limit does not hold, stop and report before stage 2. Docker is the
  fallback design.

### Stage 2: the runner

- `RunSpec`, runtime allowlist, staging, worker, Job Object, output caps,
  timeout, cleanup, single-run lock.
- Adversarial suite (see test plan) must pass before stage 3 (checkpoint 3).

### Stage 3: benchmark baseline

- Generate once per problem with the current model; grade with hidden tests.
- Report pass@1 by difficulty and split, latency, limit hits.

### Stage 4: generate-test-repair loop

- At most 2 repairs, fed only by visible-test failures (trimmed tracebacks,
  bounded length).
- Report the pass-rate change on holdout, extra latency, and any regressions
  (passing code made worse by a repair).

### Stage 5: terminal workflow

- `/run`: show the code and the limits, ask for confirmation, run a temporary
  copy, show the result. Registered as a tool with `EXECUTE` policy so the
  registry enforces approval.
- `/apply` (separate sub-stage): diff preview, explicit approval, write under
  `LOCAL_WRITE` to a workspace chosen with the folder browser.

### Stage 6 (optional): coding model comparison

- Compare `qwen3:4b-instruct` with a coding-tuned or larger model (for example
  `qwen2.5-coder:7b` or `qwen3:8b`) on the holdout, measuring pass rate,
  latency, and memory alongside Ollama's other models.

## Test plan

**Unit tests (no runtime needed):**

- The wasmtime configuration grants exactly `/lib` and `/input`, both
  read-only, with the memory limit and epoch deadline set; a golden
  comparison fails if a grant is added or a limit removed.
- The worker argv is fixed; no `shell=True` anywhere in the sandbox package
  (an AST check).
- Unknown runtime, unpinned runtime, or wrong sha256 is rejected.
- Model text containing argument- or path-like strings (`--dir C:\`,
  `; rm -rf`, `../../`) ends up only inside staged files.
- Staging enforces size and count limits and refuses symlinks and paths that
  escape the staging dir.
- Cleanup runs on success, failure, timeout, and exception (fake worker).
- Output caps and truncation flags.
- Hidden-test canary never appears in any captured model request.
- Preflight refuses in each failure mode, and chat still works when it does.

**Integration tests (runtime required; skipped with a clear reason otherwise):**

- Hello world runs; exit codes propagate; a visible test passes and fails as
  expected.
- `import socket; socket.create_connection(("1.1.1.1", 53))` fails.
- `open("C:/Windows/win.ini")`, listing `/`, and reading outside `/input` and
  `/lib` fail.
- Writing to `/input`, `/lib`, `/tmp`, or `/` fails.
- `os.fork`, `subprocess.run`, and `threading.Thread(...).start()` fail.
- `os.environ` contains only the allowlist.
- A memory bomb is stopped at the guest limit and reported; `while True: pass`
  is stopped at the deadline and reported; deep recursion is reported as a
  crash, not a hang.
- Printing 100 MiB is truncated and the worker is killed.
- Killing Kiki mid-run ends the worker (Job Object kill-on-close).
- After every test, no worker process and no `kiki-run-*` dir remain.
- Host memory, sampled during the adversarial suite, stays within the Job
  Object cap.

**Evaluations:** benchmark receipts (stage 3, stage 4, stage 6) with git
commit, model digests, `wasmtime` version, runtime sha256, limits,
per-problem results, latency, and peak worker memory.

## Human-review checkpoints

Stop and ask before:

1. Adding `wasmtime` to `pyproject.toml`. Approved in principle on October
   29; confirm the exact version at install time.
2. Downloading the CPython WASI runtime. Confirm the version and sha256.
3. Running the adversarial integration suite for the first time (it
   deliberately stresses limits on this machine; close Fusion 360 and similar
   applications first).
4. Enabling `/run` in the terminal.
5. Enabling `/apply` or any other path that writes to the user's files.
6. Downloading a coding model (stage 6).
7. Adding a writable directory, third-party packages, another language, or
   the Docker backend.
8. Relaxing any limit or grant, or adding any network access.
9. Any adversarial test failing, the stage-1 go/no-go failing, or any sign
   that hidden tests reached the model. Stop work until reviewed.

## Completion criteria

1. Every requirement under [Sandbox specification](#sandbox-specification) is
   implemented and covered by a unit test, and the adversarial suite passes.
2. A missing or unverified runtime means no execution, with an actionable
   message, while the rest of Kiki keeps working.
3. The benchmark exists with hidden tests that are provably absent from model
   context.
4. Baseline and repair-loop pass rates are recorded with receipts.
5. `/run` executes only temporary copies after confirmation; persistent edits
   require an approved diff.
6. Documentation records limits, defaults, rejected alternatives, known
   gaps, and measured tradeoffs. `THIRD_PARTY_NOTICES.md` lists `wasmtime`
   (Apache-2.0 WITH LLVM-exception) and the CPython runtime (PSF License).

## Deferred: Docker backend

Not part of this milestone. If packages, other languages, or code needing
threads or subprocesses are wanted later, add a second runner behind the same
`RunSpec` interface using Docker, after checkpoint 7. The hardening agreed on
October 29 still applies:

- `--rm --network none --read-only`, size-capped tmpfs mounts (`noexec`), and
  `/input` as a read-only bind of the staging copy.
- `--user 10001:10001 --cap-drop ALL --security-opt no-new-privileges`.
- `--pids-limit 64 --memory 512m --memory-swap 512m --cpus 1`, plus `nofile`,
  `fsize`, and `nproc` ulimits.
- `--log-driver none --ipc none --pull never`.
- An image pinned by digest (candidate read October 29: `python:3.12-slim`,
  index `sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159`).
- An argv built from typed fields, and the Docker VM capped through
  `%USERPROFILE%\.wslconfig` (2 GiB, 2 processors, swap 0) before first use.

## Implementation log format

Use the format from [RAG_PIPELINE_HANDOFF.md](RAG_PIPELINE_HANDOFF.md)
(date, stage, commit before change, files changed, behavior changed,
tests/evaluations run, result, known bugs, decision or proposal, human review
needed). Do not describe a stage as implemented until its tests and
evaluations have actually run.
