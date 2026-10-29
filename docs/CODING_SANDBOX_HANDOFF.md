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
- **Active scope: Python through WebAssembly** (`wasmtime` + CPython for
  WASI), with no Docker needed. The user accepted `wasmtime` as a Kiki
  dependency.
- **Paused: Docker and every other language** (JavaScript/TypeScript, C/C++,
  Rust, Go, Java). Reserved for a future, optional, opt-in addition. When it
  is added, the Python WebAssembly path must keep working for users without
  Docker.
- **Design target: 16 GB of RAM** with everyday desktop apps open. Kiki must
  not assume more.

History of the decision, all on October 29: the first draft used Docker only;
the second used WebAssembly first; the user then asked for all six language
groups and chose to measure both backends. The WebAssembly trial ran and
passed (see [Trial results](#trial-results)). The Docker trial could not run
safely: with normal apps open the PC had 2.3 GB of commit headroom, and
starting Docker Desktop needs about 3 GB. The user then paused Docker and the
other languages and kept the 16 GB target.

Approval of the milestone is not approval of its checkpoints. Every item under
[Human-review checkpoints](#human-review-checkpoints) still needs a yes before
it happens.

## Objective

Raise the share of Kiki's code that actually works, measured by hidden tests,
without giving generated code any path to the user's files, network, or the
stability of the host.

Success means:

1. Generated code runs only inside a disposable, locked-down sandbox.
2. A benchmark with hidden tests measures pass rate honestly, per language.
3. A bounded generate-test-repair loop measurably raises that pass rate.
4. In chat, `/run` executes a temporary copy after confirmation, and any
   change to real files is shown as a diff and applied only on approval.

## Non-goals

- Running generated code on the host outside a sandbox. There is no fallback.
- Network access from generated code, including installing packages (pip,
  npm, cargo, Maven, Go modules). Each language uses its standard library.
- GPU access, long-lived sandboxes, background services, or notebooks.
- Autonomous edits, commits, or file moves. Kiki proposes; the user approves.
- Replacing the answer model inside this milestone. That is a separately
  measured, separately approved step (stage 7).

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
  threads), 16 GB RAM, GTX 1080 8 GB. Docker 29.7.2 with Docker Desktop
  installed; its `docker-desktop` WSL 2 distribution is stopped. There is no
  `%USERPROFILE%\.wslconfig`, so Docker's VM may take up to half the RAM.
- **Memory is the binding constraint.** On October 29 the PC ran out of virtual
  memory and had to be restarted (incident in the engineering log). Fusion
  360 and Ollama alone triggered low-memory warnings. Any design that adds
  memory pressure must cap it.

## How other assistants do it

From the implementer's knowledge as of mid-2026; re-check before citing.

| Product | Where code runs | Languages |
| --- | --- | --- |
| ChatGPT code interpreter | Hosted containers (gVisor) | Python |
| Gemini code execution | Hosted sandbox | Python |
| Claude code execution tool | Hosted containers | Python, shell |
| Open WebUI | WebAssembly in the browser (Pyodide), or Jupyter | Mostly Python |
| OpenHands, SWE-agent | Docker | Any |
| E2B, Daytona | Cloud micro-VMs | Any |
| Codex CLI, Aider | The user's machine, with OS restrictions or none | Any installed toolchain |

Hosted assistants mostly limit themselves to Python. Tools that support every
language use containers or VMs. WebAssembly appears where a light footprint
matters. Kiki is local, multi-language, and memory-constrained, so it may
need both.

## Backends

| Backend | Languages | Isolation | Expected cost |
| --- | --- | --- | --- |
| **Docker** | All: Python, JavaScript/TypeScript, C/C++, Rust, Go, Java | Container inside the Docker Desktop VM (two layers) | 1-2 GB VM while Docker Desktop runs; ~1-2 s per run; images of a few GB in total |
| **WebAssembly** (candidate) | Python (JavaScript possible later) | wasmtime capability sandbox (one layer) | ~25 MB on disk; tens of MB per run; sub-second runs once compiled; no background service |

Rejected: a host subprocess with limits (no file or network boundary),
Windows Sandbox (not on Windows 11 Home), and RestrictedPython or AST
filtering (language-level and bypassable).

Dependency facts checked on October 29, 2026:

- `wasmtime` on PyPI: version 50.0.1, Apache-2.0 WITH LLVM-exception, 8.0 MB
  `win_amd64` wheel, no runtime dependencies.
- CPython for WASI: `brettcannon/cpython-wasi-build` (maintained by a CPython
  core developer), latest `v3.15.2` (October 27, 2026), 15.5 MB, PSF
  license. Prefer an older, settled release; choose at checkpoint 2.
- Docker images: official images per language, pinned by digest at
  checkpoint 4. Sizes and digests are read then, not now.

### Backend decision

**Decided October 29, 2026: WebAssembly for Python; Docker paused.** The
WebAssembly trial met every target (below). The Docker measurements were not
taken, because the machine lacked the memory headroom to start Docker Desktop
safely with everyday apps open. That is itself the deciding evidence for a
16 GB target. The original plan, kept for when Docker resumes, measured:

- **Python on both backends:** cold start, warm per-run latency, peak host
  memory (including Docker's `vmmem`), Docker VM idle memory, and whether
  every limit holds.
- **Docker for C and Java:** the fastest-compiling and the heaviest runtime,
  to size the limits for compiled languages.

Decision rule:

- **Keep WebAssembly for Python** if Docker's warm Python run exceeds 2 s, or
  Docker's VM needs more than 1 GB while idle beside Ollama. Python is the
  most common case, and `/run` for Python then works without Docker Desktop
  running.
- **Otherwise use Docker only:** one backend is simpler to secure and test.

Both outcomes keep the same `RunSpec` interface, so the choice can be
revisited later.

### Trial results

October 29, 2026. Windows 11 Home, Ryzen 5 3600, 16 GB RAM, with everyday apps
open (about 2.3 GB of commit headroom). `wasmtime` 50.0.1, CPython 3.14.9 for
WASI (zip sha256 `8de78341...29dfa2`). Harness: `evals/sandbox_trial/`.
Receipt: `evals/receipts/sandbox-trial/wasm-trial.json`. Each run used a fresh
worker process in a Job Object (768 MiB cap, kill-on-close), a 256 MiB guest
memory limit, read-only `/lib` and `/input`, and no writable directory.

| Measure | Result |
| --- | --- |
| First run (compile and cache `python.wasm`) | 1.46 s, of which compile 1.09 s; once per install |
| Warm run, hello world (whole worker process) | median 0.35 s (0.33-0.39, 10 runs) |
| Worker peak commit | 57 MB typical; 274 MB under a memory bomb or deep recursion |
| Compute workload (sieve + dict + sort) | 0.58-0.60 s versus 0.26 s native: about 2.3× slower |
| Standard library | 31 of 36 probed modules import; missing `zlib`, `sqlite3`, `multiprocessing`, `ssl`, `ctypes` |
| Host files (`C:/Windows/win.ini`, `/etc/passwd`, `/`, `/input/..`) | Blocked |
| Writes (`/input`, `/lib`, `/tmp`, `/`, `/usr`) | Blocked |
| Network (TCP, DNS) | Blocked (no socket support) |
| `subprocess`, `os.fork`, `os.system`, threads | Blocked |
| Environment | Only `PYTHONDONTWRITEBYTECODE`, `PYTHONUNBUFFERED` |
| stdin | EOF |
| Memory bomb; 1 GiB allocation | `MemoryError` at the 256 MiB limit, exit 1 |
| Infinite loop, 10 s limit | Stopped at 10.02 s and reported as `timed_out` |
| Output flood | Killed after 1 MiB; first 64 KiB kept |
| Unbounded recursion | Trap, reported as a crash (no hang) |
| Leftover staging dirs | None |

Bug found and fixed during the trial: the first version counted 10 ms epoch
ticks, and Windows timer granularity (~15.6 ms) stretched a 10 s limit to
15.4 s. The deadline is now a single tick fired by a timer at the limit.

Not yet covered: a stdlib-only coding benchmark (stage 0/3), a deliberate
attempt at a wasmtime escape (out of scope; rely on wasmtime's security
process and version pinning), and repeated runs under heavier host load.

## Architecture

```text
model answer (text)
  -> code extractor        fenced code blocks + declared language; model output is data only
  -> staging               disposable host temp dir: source files (+ visible tests)
  -> SandboxRunner         picks the backend from the runtime allowlist; fixed argv, never a shell
       Docker backend:     container (read-only root, tmpfs, /input read-only, no network,
                           non-root, no capabilities, no-new-privileges, limits)
       WebAssembly backend (Python, if kept): wasmtime worker process
                           (read-only /lib and /input, no writable dir, no sockets,
                           memory limit, deadline, Job Object)
  -> RunResult             compile and run phases: exit codes, bounded output, timings, limit flags
  -> cleanup               container or worker ended, staging dir deleted, always

benchmark:  RunResult(hidden tests) -> score only; never shown to the model
repair:     RunResult(visible tests) -> short error summary -> model (max 2 rounds)
chat /run:  confirm -> temporary copy -> RunResult shown to user
edits:      proposed change -> unified diff -> explicit approval -> write to
            the selected workspace (LOCAL_WRITE), never via the sandbox
```

### Components (proposed module `src/kiki/sandbox/`)

| Component | Responsibility | Must not |
| --- | --- | --- |
| `runtimes.py` | Allowlist: language -> backend, pinned image digest or runtime sha256, file names, fixed compile and run argv | Accept a language, image, path, flag, or argv from model or user text |
| `staging.py` | Create a per-run temp dir, write files from memory, enforce size and count limits, delete it | Copy or link from the user's workspace; follow symlinks |
| `docker.py` | Build the `docker run` argv from a `RunSpec`; run with `shell=False`; enforce wall time and output caps; remove the container | Interpolate any string into a shell; pass environment variables beyond the allowlist |
| `wasi.py`, `worker.py` | WebAssembly backend (if kept): engine and store configuration, compiled-module cache, worker process in a Job Object | Grant a writable directory, sockets, inherited environment, or host paths beyond `/lib` and `/input` |
| `preflight.py` | Fail-closed checks per backend: Docker CLI, daemon, Linux engine, VM memory cap, image digests; `wasmtime` version, runtime sha256 | Start Docker Desktop, pull images, download runtimes, or edit `.wslconfig` by itself |
| `benchmark.py` | Load problems; keep hidden tests in a separate store; grade in the sandbox; write receipts | Put hidden test text in any prompt, log shown to the model, or repair message |
| `repair.py` | Generate -> run visible tests -> summarize failure -> regenerate, at most 2 repairs | See hidden tests or their results beyond the final score |
| `edits.py` | Turn a proposed file change into a unified diff; apply only on explicit approval to a user-selected workspace | Write anywhere else; apply anything produced inside the sandbox |

### Execution is not editing

- `/run` executes a **temporary copy** only. The staging directory is created
  fresh for that run from text held in memory (the code block or files the
  user names), and deleted afterwards.
- The original workspace is **never mounted or preopened**, writable or
  otherwise. If the user asks to run a file from their project, its contents
  are copied into staging; the sandbox sees only the copy, read-only at
  `/input`.
- Nothing produced inside the sandbox is written back to the host. Its only
  outputs are stdout, stderr, exit codes, and a results file the launcher
  writes for grading.
- A persistent change to the user's files is a separate action: Kiki shows a
  unified diff, the user approves it explicitly, and application code writes it
  under the `LOCAL_WRITE` policy to a workspace the user selected.
- Execution is never triggered by the model. The model's only output is text;
  code runs because the benchmark harness or the user's `/run` said so. A turn
  in which the model read retrieved document text cannot trigger execution.

## Runtime allowlist

| Language | Backend | Image (pinned by digest at checkpoint 4) | Compile | Run |
| --- | --- | --- | --- | --- |
| Python | WebAssembly or Docker | CPython WASI build / `python:<ver>-slim` | none | `python -I -B main.py` |
| JavaScript | Docker | `node:<LTS>-slim` | none | `node main.js` |
| TypeScript | Docker | same Node image | none (Node's built-in type stripping; no type checking) | `node main.ts` |
| C | Docker | `gcc:<ver>` | `gcc -O2 -std=c17 -o /work/a.out main.c -lm` | `/work/a.out` |
| C++ | Docker | `gcc:<ver>` | `g++ -O2 -std=c++20 -o /work/a.out main.cpp` | `/work/a.out` |
| Rust | Docker | `rust:<ver>-slim` | `rustc -O --edition 2021 -o /work/a.out main.rs` | `/work/a.out` |
| Go | Docker | `golang:<ver>` | `go build -o /work/a.out main.go` (cache under `/work`) | `/work/a.out` |
| Java | Docker | `eclipse-temurin:<LTS>-jdk` | `javac -d /work Main.java` | `java -Xmx256m -cp /work Main` |

Compile and run commands are fixed in code; the model chooses only the
language (from this list) and the file contents. Standard libraries only.
Only the Python / WebAssembly row is in scope now; the Docker rows are paused.

## Docker specification

**Paused (October 29, 2026).** Kept as the specification for the future,
opt-in Docker backend. The trial harness (`evals/sandbox_trial/docker_trial.py`)
is written but has not been run.

The argv is built in code from a `RunSpec` and the runtime allowlist.
Illustrative shape (values in [Resource limits](#resource-limits)):

```text
docker run
  --rm --name kiki-run-<uuid> --label kiki.sandbox=1
  --pull never
  --network none
  --read-only
  --tmpfs /work:rw,nosuid,nodev,size=<per class>,uid=10001,gid=10001[,noexec]
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m,uid=10001,gid=10001
  --mount type=bind,source=<staging dir>,target=/input,readonly
  --user 10001:10001
  --cap-drop ALL
  --security-opt no-new-privileges
  --pids-limit <per class>
  --memory <per class> --memory-swap <same>
  --cpus <per class>
  --ulimit nofile=256:256 --ulimit fsize=<per class>
  --log-driver none
  --ipc none
  --env HOME=/tmp (+ fixed per-language variables, e.g. GOCACHE=/work/.cache)
  --workdir /work
  --entrypoint <fixed launcher interpreter>
  <image>@sha256:<pinned digest>
  <fixed launcher argv>
```

Requirements:

- **Disposable workspace per run:** a fresh staging dir and a fresh container
  for every run; `--rm` plus an explicit `docker rm -f` in a `finally` block.
- **Read-only root with bounded tmpfs:** `--read-only`; the only writable
  locations are size-capped tmpfs mounts. `/work` is `noexec` for
  interpreted languages; compiled languages need to execute their own build
  output, so `/work` allows exec for them (still inside the container, under
  every other restriction). `/input` is a read-only bind of the staging copy,
  never of the original workspace.
- **No network:** `--network none`.
- **Non-root user:** a fixed unprivileged UID/GID.
- **Dropped capabilities and no-new-privileges:** `--cap-drop ALL` and
  `--security-opt no-new-privileges`.
- **Pinned image digests:** images are referenced only as `name@sha256:...`;
  `--pull never`; preflight verifies each local image's repo digest.
- **Structured invocation:** `subprocess.run([...], shell=False)` with an argv
  assembled from typed fields. Model or user text can only become file
  contents in staging, never an argument, flag, image, environment variable,
  or mount.
- **Strict runtime allowlist:** the table above; unknown languages are
  rejected before Docker is called.
- **Cleanup after every run:** container and staging dir removed on success,
  failure, timeout, and exceptions. A startup sweep removes leftovers labeled
  `kiki.sandbox=1`.
- **Fail closed:** if the CLI is missing, the daemon is down, the engine is
  not Linux, an image or digest does not match, or the memory cap is not in
  place, the run is refused with an actionable message. There is never a
  host-execution fallback. Chat, search, and RAG keep working.

A launcher written by Kiki (not the model) copies `/input` into `/work`, runs
the fixed compile step with its own deadline, then the fixed run or test step,
and writes a results file. For Python, JavaScript, and TypeScript the launcher
is a script in that language; for compiled languages it is a small POSIX `sh`
script with fixed contents.

## WebAssembly specification

The active backend. Validated in the trial; the implementation in
`src/kiki/sandbox/` should follow `evals/sandbox_trial/wasm_worker.py` and
`jobs.py`.

- Fresh wasmtime store, instance, and worker process per run; the worker is
  started with a fixed argv (`sys.executable -I -m kiki.sandbox.worker <spec>`)
  and placed in a Windows Job Object (memory cap, kill-on-close).
- Only `/lib` (pinned stdlib) and `/input` (staging copy) are preopened, both
  read-only. No writable directory. No sockets (WASI preview 1). No process
  creation. Environment limited to `PYTHONDONTWRITEBYTECODE`,
  `PYTHONUNBUFFERED`, `PYTHONHOME=/lib`, `PYTHONSAFEPATH=1`.
- Memory limit via `Store.set_limits`; wall time via epoch interruption, with
  the parent killing the worker 2 s later as a backstop.
- Runtime pinned by version and sha256 under
  `%LOCALAPPDATA%\kiki\wasi-python\<version>`; compiled module cached there,
  keyed by wasmtime version and runtime sha256, and rebuilt if either differs.
- `max_wasm_stack` is 2 MiB (wasmtime's async-stack ceiling), run on a host
  thread with a 16 MiB native stack. The 512 KiB default trapped
  `@functools.cache` recursion below 500 levels; 2 MiB allows about 1,200 in a
  single call (measured; 1,500 fails). Plain recursion is unaffected (100,000+).
- Wall time is a single epoch tick fired by a timer at the deadline (not many
  small ticks; Windows timer granularity makes those drift).
- Output is captured with `stdout_custom`/`stderr_custom` callbacks that keep
  the first 64 KiB / 16 KiB and stop the guest after 1 MiB.
- `wasmtime` pinned to an exact version in `pyproject.toml` (currently the
  `sandbox` extra; it becomes a required dependency when the runner ships).
  If the runtime is missing, Python runs refuse with the setup command. Never
  the host. (If the Docker backend is added later, it may serve as a second
  option.)

## Resource limits

Starting values; changes go through checkpoint 10. The WebAssembly column
was validated in the trial. The Docker columns apply only if that backend
resumes.

| Limit | WebAssembly (Python) | Docker, interpreted (Python, JS, TS) | Docker, compiled (C, C++, Rust, Go, Java) |
| --- | --- | --- | --- |
| Wall time | 10 s run | 10 s run | 30 s compile + 10 s run |
| Benchmark case | 30 s | 30 s | 30 s compile + 30 s tests |
| CPU | 1 (single-threaded) | 1 | 2 compile, then 1 for the run phase if separable; otherwise 2 |
| Memory | 256 MiB guest; 768 MiB worker (Job Object) | 512 MiB, no swap | 1 GiB, no swap (Java heap 256 MiB) |
| Processes and threads | none possible | 64 | 256 (compilers and the JVM use many threads) |
| Disk | no writes | `/work` 64 MiB noexec, `/tmp` 16 MiB | `/work` 256 MiB exec, `/tmp` 16 MiB |
| Output | 64 KiB stdout + 16 KiB stderr kept; killed after 1 MiB | same | same, per phase |
| Input staging | 2 MiB, 50 files | same | same |

Shared: one run at a time (host lock). Docker VM capped through
`%USERPROFILE%\.wslconfig` at 2 GiB RAM, 2 processors, swap 0 to start;
raising it to 3 GiB for compiled languages needs evidence from the trial and
checkpoint 10.

Each limit hit is reported (`compile_timed_out`, `timed_out`, `oom_killed`,
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
| Read or alter user files | `open("C:/Users/...")`, `rm -rf` | No host mounts except the read-only staging copy; read-only root or read-only preopens; nothing written back | None known within Docker's or wasmtime's guarantees |
| Exfiltration or downloads | HTTP requests, DNS, package installs | `--network none`; no WASI sockets | Covert channels via output text (bounded by output caps) |
| Privilege escalation | setuid binaries, capabilities | Non-root, `--cap-drop ALL`, `no-new-privileges` | Kernel or Docker vulnerabilities; the VM is a second layer |
| Sandbox escape (WebAssembly) | A wasmtime or Cranelift bug | Pinned, current wasmtime; separate worker in a Job Object | An escape runs with the user's rights; one layer, versus two for Docker. Accepted for standard-library Python only |
| Injection into the invocation | Model text becoming `-v C:\:/host` or a compiler flag | Argv and compile commands fixed per language; text only becomes file contents | Bugs in the argv builder (tested exhaustively) |
| Malicious build steps | `#include "/etc/shadow"`, Go `//go:generate`, Rust `build.rs`, `include_str!` | Compilers run inside the same container with the same limits; no build tools that fetch packages; only the container's own files are reachable | Compiler bugs (inside the container) |
| Resource exhaustion | Fork bomb, memory bomb, infinite loop, disk fill, output flood, slow compile | Limits table; one run at a time; VM capped | Docker VM startup itself uses RAM |
| Persistence | Background processes | `--rm`, kill on timeout, fresh container per run, startup sweep; Job Object kill-on-close | None known |
| Supply chain | Tampered or changed image or runtime | Digest pinning, `--pull never`, preflight checks; runtime sha256 | Trust in the official images and publishers at review time |
| Hidden-test leakage | Tests copied into prompts or repair feedback | Separate store; only the grader reads them; canary test | Model memorization of public problems (use original variants) |
| Benchmark gaming | Code that reads test files or prints "OK" | Hidden tests staged only for grading; results judged by comparing outputs, not by trusting stdout claims | Weak test design; review the tests |
| Unintended execution | Model or document text triggering a run | Execution only from the benchmark harness or `/run` + confirmation; tools with `EXECUTE` risk require approval | User approving without reading (show the code first) |
| Unapproved edits | Writing results back to the workspace | Edits only via diff + explicit approval under `LOCAL_WRITE` | User approving a bad diff |

## Hidden benchmark tests

- Problems are **language-neutral**: each defines a stdin/stdout format, and
  every test is an input with its expected output. The same hidden tests then
  grade every language without a test harness per language.
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
- Results are reported per language. A 4B model is expected to be weaker
  outside Python and JavaScript; the benchmark shows by how much.

## Staged implementation

Each stage ends with focused tests, a receipt where a model is involved, an
engineering-log entry in the existing format, and a separate commit.

### Stage 0: baseline and benchmark design (no execution)

Update (October 29): at the user's request the first measurements use
standardized benchmarks (HumanEval+, MBPP+, LeetCodeDataset Medium/Hard),
graded in the sandbox by `evals/sandbox_trial/coding_benchmark.py`. The
original problems below remain the plan for a contamination-free holdout.

- Re-run `kiki eval-chat` and save a receipt.
- Write about 40 original language-neutral problems (10 easy, 20 medium, 10
  hard) with visible examples and hidden stdin/stdout tests; split 15
  development / 25 holdout.
- Review the tests themselves (do they test the stated behavior?).

### Stage 1: setup and backend trial

- **Done for WebAssembly (October 29):** `wasmtime` 50.0.1 installed as the
  `sandbox` extra, CPython 3.14.9 for WASI downloaded and verified, trial run
  and passed ([Trial results](#trial-results)).
- **Done (October 29):** `kiki sandbox setup` (download, verify sha256,
  unpack safely, compile, record checksums in a manifest) and
  `kiki sandbox doctor`; every missing piece produces a refusal with the fix.
- **Paused:** the Docker half (images, Docker trial). `%USERPROFILE%\.wslconfig`
  was created with the 2 GB / 2 processor / no-swap cap and left in place
  as a guard; delete it to undo.

### Stage 2: the runner, Python first

- `RunSpec`, runtime allowlist, staging, the WebAssembly backend, output
  caps, timeouts, cleanup, single-run lock. Promote `wasmtime` from the
  `sandbox` extra to a required dependency.
- **Done (October 29):** `src/kiki/sandbox/` (`runtime`, `limits`,
  `staging`, `jobs`, `wasi`, `worker`, `runner`, `preflight`, `setup`);
  `wasmtime` is required. 28 tests in `tests/test_sandbox.py`: unit tests for
  every guard, plus integration tests (host files, writes, network,
  processes, environment, time, memory, output, recursion, cleanup) that run
  when the runtime is installed. Not reachable from chat; `/run` is
  checkpoint 7.
- **Approved and done (October 29), checkpoint 10:** `sortedcontainers`
  2.4.0, pinned by wheel checksum, unpacked by setup into a read-only
  `/packages` folder (a third read-only grant), tree checksum verified by
  preflight. Pure Python, no dependencies. Further packages need a new yes.
- Adversarial suite (see test plan) must pass before stage 3 (checkpoint 5).

### Stage 3: benchmark baseline (Python)

- Generate once per problem with the current model; grade with hidden tests.
- Report pass@1 by difficulty and split, latency, limit hits.

### Stage 4: generate-test-repair loop

- At most 2 repairs, fed only by visible-test failures (trimmed errors and
  compiler messages, bounded length).
- Report the pass-rate change on holdout, extra latency, and any regressions
  (passing code made worse by a repair).

### Stage 5: terminal workflow

- `/run`: show the code, language, and limits, ask for confirmation, run a
  temporary copy, show the result. Registered as a tool with `EXECUTE` policy
  so the registry enforces approval.
- `/apply` (separate sub-stage): diff preview, explicit approval, write under
  `LOCAL_WRITE` to a workspace chosen with the folder browser.

### Stage 6: more languages, in waves (paused)

Paused on October 29, 2026; a future, optional, opt-in addition. Resuming
requires the Docker trial to run first, with at least 5 GB of commit headroom,
and its results reviewed. Each wave: pin and pull images (checkpoint 4), add allowlist entries, run the
adversarial suite for the new runtimes, add a per-language benchmark row.

1. JavaScript and TypeScript.
2. C and C++.
3. Go, Rust, and Java.

### Stage 7 (optional): coding model comparison

- Compare `qwen3:4b-instruct` with a coding-tuned or larger model (for example
  `qwen2.5-coder:7b` or `qwen3:8b`) on the holdout across languages, measuring
  pass rate, latency, and memory alongside Ollama's other models.

## Test plan

**Unit tests (no Docker or runtime needed):**

- The Docker argv builder produces exactly the required flags per language
  class, in a golden-file comparison; adding or removing a security flag fails
  the test. The same for the wasmtime grants and limits.
- No `shell=True` anywhere in the sandbox package (an AST check).
- Unknown language, image tag without a digest, or extra mounts are rejected.
- Model text containing flag-like strings (`--privileged`, `-v C:\:/x`,
  `; rm -rf`, `-fplugin=`) ends up only inside staged files.
- Staging enforces size and count limits and refuses symlinks and paths that
  escape the staging dir.
- Cleanup runs on success, failure, timeout, and exception (fake runner).
- Output caps and truncation flags.
- Hidden-test canary never appears in any captured model request.
- Preflight refuses in each failure mode (fake `docker` responses, missing
  runtime), and chat still works when it does.

**Integration tests (backend required; skipped with a clear reason otherwise),
for every enabled language:**

- Hello world compiles and runs; exit codes propagate; a visible test passes
  and fails as expected.
- Network attempts fail (TCP connect and DNS).
- Reading host paths fails; writing to `/`, `/usr`, or `/input` fails; writing
  past the `/work` cap fails.
- Not root; no capabilities; `NoNewPrivs: 1` (Docker).
- A fork bomb is contained by the PID limit; a memory bomb is killed and
  reported; an infinite loop is killed at the deadline and reported; a
  compile that never finishes (for example a template or macro explosion) is
  killed at the compile deadline.
- Printing 100 MiB is truncated and the run is killed.
- After every test, no container labeled `kiki.sandbox=1`, no worker process,
  and no staging dir remain.
- Host memory, sampled during the adversarial suite, stays within the caps.

**Evaluations:** backend-trial receipt (stage 1) and benchmark receipts
(stages 3, 4, 6, 7) with git commit, model digests, image digests or runtime
sha256, limits, per-problem and per-language results, latency, and peak host
memory.

## Human-review checkpoints

Stop and ask before:

1. Adding `wasmtime` to `pyproject.toml`. Done October 29 (50.0.1, `sandbox`
   extra), under the user's instruction to run the trials; making it required
   happens in stage 2.
2. Downloading the CPython WASI runtime. Done October 29 (3.14.9, sha256
   recorded); changing the version needs a new yes.
3. Creating or editing `%USERPROFILE%\.wslconfig`, or restarting WSL or
   Docker Desktop. The file was created on October 29 for the trial.
4. Pulling any Docker image (paused). Show the image, digest, and size;
   images for compiled languages are large (hundreds of MB to over 1 GB each).
5. Running the adversarial integration suite for the first time for each
   backend or language wave (close Fusion 360 and similar applications first).
6. The backend decision after the stage-1 trial. Decided October 29:
   WebAssembly for Python, Docker paused. Resuming Docker is a new decision.
7. Enabling `/run` in the terminal.
8. Enabling `/apply` or any other path that writes to the user's files.
9. Downloading a coding model (stage 7).
10. Adding packages, network access, writable host paths, or another
    language beyond the allowlist; relaxing any limit or security flag.
11. Any adversarial test failing, or any sign that hidden tests reached the
    model. Stop work until reviewed.

## Completion criteria

1. Every requirement under
   [WebAssembly specification](#webassembly-specification) and the shared
   requirements (disposable staging, no writable host paths, structured
   invocation, allowlist, cleanup, fail closed) is implemented and covered by
   a unit test, and the adversarial suite passes. The Docker specification
   applies only if that backend resumes.
2. An unavailable backend means no execution, with an actionable message,
   while the rest of Kiki keeps working.
3. The benchmark exists with hidden tests that are provably absent from model
   context.
4. Baseline and repair-loop pass rates are recorded per language with
   receipts.
5. `/run` executes only temporary copies after confirmation; persistent edits
   require an approved diff.
6. Documentation records limits, defaults, the backend decision with its
   measurements, rejected alternatives, known gaps, and measured tradeoffs.
   `THIRD_PARTY_NOTICES.md` lists `wasmtime` and the CPython runtime if used.

## Implementation log format

Use the format from [RAG_PIPELINE_HANDOFF.md](RAG_PIPELINE_HANDOFF.md)
(date, stage, commit before change, files changed, behavior changed,
tests/evaluations run, result, known bugs, decision or proposal, human review
needed). Do not describe a stage as implemented until its tests and
evaluations have actually run.
