from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from kiki.resilience import ErrorCode, KikiError
from kiki.run_command import code_from_answer, run_command
from kiki.sandbox import RunLimits, RunResult
from kiki.sandbox.preflight import require
from kiki.sandbox.runtime import RuntimePaths, default_home
from kiki.terminal import TerminalSession, _handle_command

ANSWER = """Here is the approach.

```javascript
console.log("not this")
```

```python
print("first draft")
```

Final version:

```python
def twice(n):
    return n * 2

print(twice(21))
```
"""


class FakeRunner:
    def __init__(self, result: RunResult | None = None, error: Exception | None = None) -> None:
        self.limits = RunLimits()
        self.calls: list[tuple[dict[str, str], str]] = []
        self.result = result or RunResult(exit_code=0, stdout="42\n", stderr="", duration_s=0.4,
                                          peak_memory_mb=75)
        self.error = error

    def run(self, files: dict[str, str], entry: str = "main.py", limits: Any = None) -> RunResult:
        self.calls.append((dict(files), entry))
        if self.error:
            raise self.error
        return self.result


def _console() -> Console:
    return Console(record=True, width=100)


def test_code_from_answer_takes_the_last_python_block() -> None:
    assert code_from_answer(ANSWER).startswith("def twice(n):")
    assert code_from_answer("```\nprint(1)\n```") == "print(1)\n"
    assert code_from_answer("```js\nx()\n```") is None
    assert code_from_answer("no code here") is None
    assert code_from_answer("```python\n   \n```") is None


def test_declining_never_runs() -> None:
    runner, console = FakeRunner(), _console()

    result = run_command(console, answer=ANSWER, mode="chat", argument=None,
                         read=lambda prompt: "", runner=runner)

    assert result is None and runner.calls == []
    output = console.export_text()
    assert "print(twice(21))" in output and "no access to your files" in output
    assert "Not run." in output


def test_confirming_runs_the_shown_code_and_shows_output() -> None:
    runner, console = FakeRunner(), _console()

    result = run_command(console, answer=ANSWER, mode="chat", argument=None,
                         read=lambda prompt: "y", runner=runner)

    assert result is not None and result.ok
    assert runner.calls == [({"main.py": code_from_answer(ANSWER)}, "main.py")]
    output = console.export_text()
    assert "Finished" in output and "42" in output


def test_rag_answers_carry_a_warning() -> None:
    console = _console()
    run_command(console, answer=ANSWER, mode="rag", argument=None,
                read=lambda prompt: "n", runner=FakeRunner())
    assert "based on your documents" in console.export_text()


def test_file_argument_runs_a_copy(tmp_path: Path) -> None:
    script = tmp_path / "solve.py"
    script.write_text("print('from file')\n", encoding="utf-8")
    runner = FakeRunner()

    run_command(_console(), answer=None, mode="chat", argument=script,
                read=lambda prompt: "yes", runner=runner)

    assert runner.calls == [({"solve.py": "print('from file')\n"}, "solve.py")]
    assert script.read_text(encoding="utf-8") == "print('from file')\n"


def test_non_python_or_missing_files_are_refused(tmp_path: Path) -> None:
    runner, console = FakeRunner(), _console()
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    run_command(console, answer=None, mode="chat", argument=tmp_path / "notes.txt",
                read=lambda prompt: "y", runner=runner)
    run_command(console, answer=None, mode="chat", argument=tmp_path / "missing.py",
                read=lambda prompt: "y", runner=runner)
    assert runner.calls == []
    output = console.export_text()
    assert "Only .py files" in output and "File not found" in output


@pytest.mark.parametrize(("result", "expected"), [
    (RunResult(None, "", "", timed_out=True), "time limit"),
    (RunResult(None, "x", "", output_killed=True, output_truncated=True), "too much output"),
    (RunResult(1, "", "MemoryError", memory_exceeded=True), "memory limit"),
    (RunResult(None, "", "", crashed="wasm trap: call stack exhausted"), "Crashed"),
    (RunResult(2, "", "Traceback ...\nValueError: bad"), "Exited with code 2"),
])
def test_limits_and_failures_are_explained(result: RunResult, expected: str) -> None:
    console = _console()
    run_command(console, answer=ANSWER, mode="chat", argument=None,
                read=lambda prompt: "y", runner=FakeRunner(result))
    assert expected in console.export_text()


def test_unavailable_sandbox_is_reported_not_raised() -> None:
    error = KikiError("Code execution is unavailable: run `kiki sandbox setup`.",
                      code=ErrorCode.SERVICE_UNAVAILABLE)
    console = _console()
    result = run_command(console, answer=ANSWER, mode="chat", argument=None,
                         read=lambda prompt: "y", runner=FakeRunner(error=error))
    assert result is None and "kiki sandbox setup" in console.export_text()


def test_terminal_run_without_an_answer_explains(tmp_path: Path) -> None:
    session = TerminalSession(tmp_path / "index.sqlite3")
    console = _console()

    assert _handle_command(console, session, "/run") == (False, None)
    assert "no Python code block" in console.export_text()


def _installed() -> bool:
    try:
        require(RuntimePaths(default_home()))
        return True
    except KikiError:
        return False


@pytest.mark.skipif(not _installed(), reason="run `kiki sandbox setup` first")
def test_end_to_end_run_in_the_real_sandbox() -> None:
    console = _console()
    result = run_command(console, answer=ANSWER, mode="chat", argument=None,
                         read=lambda prompt: "y")
    assert result is not None and result.ok and result.stdout.strip() == "42"
    assert "Finished" in console.export_text()
