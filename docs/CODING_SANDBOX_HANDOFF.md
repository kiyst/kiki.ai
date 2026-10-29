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

- Docker as the isolation boundary, with Docker Desktop's VM memory capped.
- Execution triggered by benchmarks automatically, and in chat only by `/run`
  with an explicit confirmation.

Approval of the milestone is not approval of its checkpoints. Every item under
[Human-review checkpoints](#human-review-checkpoints) still needs a yes before
it happens.

## Objective

Raise the share of Kiki's code that actually works, measured by hidden tests,
without giving generated code any path to the user's files, network, or the
stability of the host.

Success means:

1. Generated code runs only inside a disposable, locked-down container.
2. A benchmark with hidden tests measures pass rate honestly.
3. A bounded generate-test-repair loop measurably raises that pass rate.
4. In chat, `/run` executes a temporary copy after confirmation, and any
   change to real files is shown as a diff and applied only on approval.

## Non-goals

- Running anything on the host outside the container. There is no fallback.
- Network access from generated code, including installing packages.
- Languages other than Python in the first version.
- GPU access inside the sandbox.
- Long-lived containers, background services, or notebooks.
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
- **Machine:** Windows 11, Ryzen 5 3600 (12 threads), 16 GB RAM, GTX 1080
  8 GB. Docker 29.7.2 with Docker Desktop installed; its `docker-desktop` WSL 2
  distribution is stopped. There is no `%USERPROFILE%\.wslconfig`, so Docker's
  VM may take up to half the RAM.
- **Memory is the binding constraint.** On October 29 the PC ran out of virtual
  memory and had to be restarted (incident in the engineering log). Fusion
  360 and Ollama alone triggered low-memory warnings. Any design that adds
  memory pressure must cap it.

## Architecture

```text
model answer (text)
  -> code extractor            pulls fenced Python blocks; model output is data only
  -> staging                   disposable host temp dir: main.py (+ visible tests)
  -> SandboxRunner             fixed argv to `docker run`, never a shell string
       container: read-only root, tmpfs /work, /input read-only, no network,
                  non-root, no capabilities, no-new-privileges, limits
  -> RunResult                 exit code, bounded stdout/stderr, timings, limit flags
  -> cleanup                   container removed, staging dir deleted, always

benchmark:  RunResult(hidden tests) -> score only; never shown to the model
repair:     RunResult(visible tests) -> short error summary -> model (max 2 rounds)
chat /run:  confirm -> temporary copy -> RunResult shown to user
edits:      proposed change -> unified diff -> explicit approval -> write to
            the selected workspace (LOCAL_WRITE), never via the container
```

### Components (proposed module `src/kiki/sandbox/`)

| Component | Responsibility | Must not |
| --- | --- | --- |
| `runtimes.py` | Allowlist: runtime name -> pinned image digest, interpreter argv, file layout | Accept a runtime, image, or argv from model or user text |
| `staging.py` | Create a per-run temp dir, write files from memory, enforce size and count limits, delete it | Copy or link from the user's workspace; follow symlinks |
| `docker.py` | Build the `docker run` argv from a `RunSpec`; run via `subprocess` with a list (no `shell=True`); enforce wall time and output caps; remove the container | Interpolate any string into a shell; pass environment variables beyond the allowlist |
| `preflight.py` | Fail-closed checks: CLI present, daemon reachable, Linux engine, image present with the pinned digest, VM memory cap set | Start Docker Desktop, pull images, or edit `.wslconfig` by itself |
| `benchmark.py` | Load problems; keep hidden tests in a separate store; grade in the sandbox; write receipts | Put hidden test text in any prompt, log shown to the model, or repair message |
| `repair.py` | Generate -> run visible tests -> summarize failure -> regenerate, at most 2 repairs | See hidden tests or their results beyond the final score |
| `edits.py` | Turn a proposed file change into a unified diff; apply only on explicit approval to a user-selected workspace | Write anywhere else; apply anything produced inside the container |

### Execution is not editing

- `/run` executes a **temporary copy** only. The staging directory is created
  fresh for that run from text held in memory (the code block or files the
  user names), and deleted afterwards.
- The original workspace is **never mounted** into a container, writable or
  otherwise. If the user asks to run a file from their project, its contents
  are copied into staging; the container sees only the copy, read-only at
  `/input`.
- Nothing produced inside the container is written back to the host.
- A persistent change to the user's files is a separate action: Kiki shows a
  unified diff, the user approves it explicitly, and application code writes it
  under the `LOCAL_WRITE` policy to a workspace the user selected.
- Execution is never triggered by the model. The model's only output is text;
  code runs because the benchmark harness or the user's `/run` said so. A turn
  in which the model read retrieved document text cannot trigger execution.

## Container specification

The argv is built in code from a `RunSpec` and the runtime allowlist.
Illustrative shape (values in [Resource limits](#resource-limits)):

```text
docker run
  --rm --name kiki-run-<uuid> --label kiki.sandbox=1
  --pull never
  --network none
  --read-only
  --tmpfs /work:rw,noexec,nosuid,nodev,size=64m,uid=10001,gid=10001
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m,uid=10001,gid=10001
  --mount type=bind,source=<staging dir>,target=/input,readonly
  --user 10001:10001
  --cap-drop ALL
  --security-opt no-new-privileges
  --pids-limit 64
  --memory 512m --memory-swap 512m
  --cpus 1
  --ulimit nofile=64:64 --ulimit fsize=16777216 --ulimit nproc=64
  --log-driver none
  --ipc none
  --env PYTHONDONTWRITEBYTECODE=1 --env PYTHONUNBUFFERED=1 --env HOME=/tmp
  --workdir /work
  --entrypoint /usr/local/bin/python
  python@sha256:<pinned digest>
  -I -B /input/kiki_launcher.py
```

Requirements:

- **Disposable workspace per run:** a fresh staging dir and a fresh container
  for every run; `--rm` plus an explicit `docker rm -f` in a `finally` block.
- **Read-only root with bounded tmpfs:** `--read-only`; the only writable
  locations are size-capped tmpfs mounts. `/input` is a read-only bind of the
  staging copy, never of the original workspace.
- **No network:** `--network none`.
- **Non-root user:** a fixed unprivileged UID/GID.
- **Dropped capabilities and no-new-privileges:** `--cap-drop ALL` and
  `--security-opt no-new-privileges`.
- **Pinned image digest:** images are referenced only as `name@sha256:...`;
  `--pull never`; preflight verifies the local image's repo digest matches.
  Candidate, to be confirmed at the image checkpoint: `python:3.12-slim`
  index digest `sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159`
  (linux/amd64 manifest `sha256:1148dbb014615300fa7e713b2f94f550c0d1c69780c0805f84f093ceee34dd0b`),
  read from Docker Hub on October 29, 2026.
- **Structured invocation:** `subprocess.run([...], shell=False)` with an argv
  assembled from typed fields. Model or user text can only become file
  contents in staging, never an argument, flag, image, environment variable,
  or mount.
- **Strict runtime allowlist:** one runtime, `python3.12`, mapping to the
  pinned image and a fixed interpreter argv. Unknown runtimes are rejected
  before Docker is called. Tests use stdlib `unittest`, so no packages are
  installed.
- **Cleanup after every run:** container and staging dir removed on success,
  failure, timeout, and exceptions. A startup sweep removes leftovers labeled
  `kiki.sandbox=1`.
- **Fail closed:** if the CLI is missing, the daemon is down, the engine is
  not Linux, the image or digest does not match, or the memory cap is not in
  place, the run is refused with an actionable message. There is never a
  host-execution fallback.

The launcher (`kiki_launcher.py`, written by Kiki, not the model) copies
`/input` into `/work`, then runs the program or the test module with fixed
arguments, so the user code runs in the size-capped tmpfs.

## Resource limits

| Limit | Value | Enforced by | Why |
| --- | --- | --- | --- |
| Wall time | 10 s run, 30 s benchmark case | Host timer, then `docker kill` | Infinite loops |
| CPU | 1 core | `--cpus 1` | Keep Ollama and the desktop responsive |
| Memory | 512 MiB, no swap | `--memory`, `--memory-swap` | Memory bombs; the host is tight |
| Processes | 64 | `--pids-limit`, `--ulimit nproc` | Fork bombs |
| Open files | 64 | `--ulimit nofile` | Descriptor exhaustion |
| Disk | 64 MiB `/work`, 16 MiB `/tmp`, 16 MiB per file | tmpfs `size=`, `--ulimit fsize` | Disk filling; read-only root |
| Output | 64 KiB stdout + 16 KiB stderr kept; kill after 1 MiB read | Host reader | Flooding the terminal or model context |
| Input staging | 2 MiB total, 50 files | `staging.py` | Bounded copies |
| Concurrency | 1 container at a time | Host lock | One heavy job at a time |
| Docker VM | 2 GiB RAM, 2 processors, swap 0 | `.wslconfig` (checkpoint) | Prevent a repeat of the out-of-memory crash |

Each limit hit is reported (`timed_out`, `oom_killed`, `output_truncated`, and
so on) instead of looking like an ordinary failure.

## Threat model

**Assets:** the user's files and credentials; network access and anything
reachable from it; host stability (RAM, disk, responsiveness); Kiki's own
index, memory, and persona files; the integrity of benchmark results.

**Untrusted inputs:** model-generated code (buggy or adversarial); prompt
injection from retrieved documents or pasted text that steers the model's
code; user-supplied code run via `/run`.

| Threat | Example | Mitigation | Residual risk |
| --- | --- | --- | --- |
| Read or alter user files | `open("C:/Users/...")`, `shutil.rmtree` | No host mounts except the read-only staging copy; read-only root; nothing written back | None known within Docker's guarantees |
| Exfiltration or downloads | HTTP requests, DNS, `pip install` | `--network none` | Covert channels via output text (bounded by output caps) |
| Privilege escalation | setuid binaries, capabilities | Non-root, `--cap-drop ALL`, `no-new-privileges` | Kernel or Docker vulnerabilities; Docker Desktop's VM adds a second boundary |
| Container escape via Docker flags | Model text becoming `-v C:\:/host` | Argv built from typed fields; text only becomes file contents | Bugs in the argv builder (tested exhaustively) |
| Resource exhaustion | Fork bomb, memory bomb, infinite loop, disk fill, output flood | Limits table; one container at a time; VM capped | Docker VM startup itself uses RAM |
| Persistence | Background processes, crontab | `--rm`, kill on timeout, fresh container per run, startup sweep | None known |
| Supply chain | Tampered or changed image | Digest pinning, `--pull never`, preflight digest check | Trust in the official image at review time |
| Hidden-test leakage | Tests copied into prompts or repair feedback | Separate store; only the grader reads them; canary test | Model memorization of public problems (use original variants) |
| Benchmark gaming | Code that reads test files or prints "OK" | Hidden tests mounted only for grading; grader checks results structurally | Weak test design; review the tests |
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

## Staged implementation

Each stage ends with focused tests, a receipt where a model is involved, an
engineering-log entry in the existing format, and a separate commit.

### Stage 0: baseline and benchmark design (no execution)

- Re-run `kiki eval-chat` and save a receipt.
- Write about 40 original Python problems (10 easy, 20 medium, 10 hard) with
  visible examples and hidden tests; split 15 development / 25 holdout.
  Original wording and variants reduce memorization.
- Review the tests themselves (do they test the stated behavior?).

### Stage 1: preflight, fail-closed (no execution)

- `kiki sandbox doctor`: CLI, daemon, Linux engine, VM memory cap, image digest.
- Every missing piece produces a refusal with the fix; nothing starts Docker,
  pulls images, or edits configuration on its own.

### Stage 2: the runner

- `RunSpec`, runtime allowlist, staging, argv builder, output caps, timeout,
  cleanup, single-container lock.
- Adversarial suite (see test plan) must pass before stage 3.

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

**Unit tests (no Docker):**

- Argv builder produces exactly the required flags, in a golden-file
  comparison; adding or removing a security flag fails the test.
- No `shell=True` anywhere in the sandbox package (an AST check).
- Unknown runtime, image tag without a digest, or extra mounts are rejected.
- Model text containing flag-like strings (`--privileged`, `-v C:\:/x`,
  `; rm -rf`) ends up only inside staged files.
- Staging enforces size and count limits and refuses symlinks and paths that
  escape the staging dir.
- Cleanup runs on success, failure, timeout, and exception (fake runner).
- Output caps and truncation flags.
- Hidden-test canary never appears in any captured model request.
- Preflight refuses in each failure mode (fake `docker` responses).

**Integration tests (Docker required; skipped with a clear reason otherwise):**

- Hello world runs; exit codes propagate.
- `socket.create_connection(("1.1.1.1", 53))` fails; DNS fails.
- Writing to `/`, `/usr`, or `/input` fails; writing over 64 MiB to `/work`
  fails.
- `os.getuid() != 0`; `/proc/self/status` shows no capabilities and
  `NoNewPrivs: 1`.
- A fork bomb is contained by the PID limit; a memory bomb is OOM-killed and
  reported; `while True: pass` is killed at the timeout and reported.
- Printing 100 MiB is truncated and the run is killed.
- After every test, no container labeled `kiki.sandbox=1` and no staging dir
  remain.
- Host memory, sampled during the adversarial suite, stays within the Docker VM
  cap.

**Evaluations:** benchmark receipts (stage 3, stage 4, stage 6) with git
commit, model digests, image digest, limits, per-problem results, latency,
and peak host memory.

## Human-review checkpoints

Stop and ask before:

1. Creating or editing `%USERPROFILE%\.wslconfig` (the VM memory cap), or
   restarting WSL or Docker Desktop.
2. Pulling the Python image. Confirm the digest above (or a newer one) at that
   time.
3. Running the adversarial integration suite for the first time (it
   deliberately stresses limits on this machine; close Fusion 360 and similar
   applications first).
4. Enabling `/run` in the terminal.
5. Enabling `/apply` or any other path that writes to the user's files.
6. Downloading a coding model (stage 6).
7. Adding a runtime other than Python, any package to the image, or a derived
   image.
8. Relaxing any limit or security flag, or adding any network access.
9. Any adversarial test failing, or any sign that hidden tests reached the
   model. Stop work until reviewed.

## Completion criteria

1. Every requirement under [Container specification](#container-specification)
   is implemented and covered by a unit test, and the adversarial suite passes.
2. Docker unavailable means no execution, with an actionable message.
3. The benchmark exists with hidden tests that are provably absent from model
   context.
4. Baseline and repair-loop pass rates are recorded with receipts.
5. `/run` executes only temporary copies after confirmation; persistent edits
   require an approved diff.
6. Documentation records limits, defaults, rejected alternatives, known
   gaps, and measured tradeoffs.

## Implementation log format

Use the format from [RAG_PIPELINE_HANDOFF.md](RAG_PIPELINE_HANDOFF.md)
(date, stage, commit before change, files changed, behavior changed,
tests/evaluations run, result, known bugs, decision or proposal, human review
needed). Do not describe a stage as implemented until its tests and
evaluations have actually run.
