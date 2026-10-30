from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from kiki.apply_command import (
    ApplyError,
    apply_command,
    last_code_block,
    plan_change,
    resolve_target,
    write_change,
)
from kiki.model_client import ChatOutcome
from kiki.terminal import TerminalSession, _handle_command

ANSWER = """Fixed version:

```python
def add(a, b):
    return a + b
```
"""


def _console() -> Console:
    return Console(record=True, width=120)


def _apply(workspace: Path | None, argument: str | None, reply: str = "y",
           answer: str = ANSWER, backups: Path | None = None) -> tuple[Path | None, str, list[str]]:
    console, prompts = _console(), []

    def read(prompt: str) -> str:
        prompts.append(prompt)
        return reply

    written = apply_command(console, answer=answer, workspace=workspace,
                            argument=Path(argument) if argument else None,
                            backups=backups or (workspace or Path(".")) / ".backups", read=read)
    return written, console.export_text(), prompts


def test_last_code_block_takes_any_language() -> None:
    assert last_code_block(ANSWER) == ("python", "def add(a, b):\n    return a + b\n")
    assert last_code_block("```js\nx()\n```\n```toml\na = 1\n```") == ("toml", "a = 1\n")
    assert last_code_block("no code") is None


def test_new_file_is_shown_as_a_diff_and_written_on_yes(tmp_path: Path) -> None:
    written, output, prompts = _apply(tmp_path, "src_add.py")

    assert written == tmp_path / "src_add.py"
    assert written.read_text(encoding="utf-8") == "def add(a, b):\n    return a + b\n"
    assert "+def add(a, b):" in output and "New file" in output
    assert prompts == ["Write this to src_add.py? [y/N] "]


def test_declining_writes_nothing(tmp_path: Path) -> None:
    target = tmp_path / "add.py"
    target.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")

    written, output, _ = _apply(tmp_path, "add.py", reply="n")

    assert written is None and "Not written." in output
    assert target.read_text(encoding="utf-8") == "def add(a, b):\n    return a - b\n"
    assert "-    return a - b" in output and "+    return a + b" in output


def test_existing_file_is_backed_up_and_keeps_crlf(tmp_path: Path) -> None:
    target = tmp_path / "add.py"
    target.write_bytes(b"def add(a, b):\r\n    return a - b\r\n")
    backups = tmp_path / "backups"

    written, output, _ = _apply(tmp_path, "add.py", backups=backups)

    assert written == target
    assert target.read_bytes() == b"def add(a, b):\r\n    return a + b\r\n"
    saved = list(backups.rglob("*.bak"))
    assert len(saved) == 1 and saved[0].read_bytes() == b"def add(a, b):\r\n    return a - b\r\n"
    assert "Previous version saved" in output


@pytest.mark.parametrize("argument", ["../outside.py", "C:/Windows/evil.py", "sub/../../x.py"])
def test_paths_outside_the_workspace_are_refused(tmp_path: Path, argument: str) -> None:
    workspace = tmp_path / "work"
    workspace.mkdir()
    with pytest.raises(ApplyError, match="outside the workspace"):
        resolve_target(workspace, Path(argument))


def test_folders_missing_parents_and_binary_files_are_refused(tmp_path: Path) -> None:
    (tmp_path / "folder").mkdir()
    with pytest.raises(ApplyError, match="is a folder"):
        resolve_target(tmp_path, Path("folder"))
    with pytest.raises(ApplyError, match="Folder does not exist"):
        resolve_target(tmp_path, Path("missing/x.py"))
    binary = tmp_path / "image.bin"
    binary.write_bytes(b"\xff\xfe\x00\x81")
    with pytest.raises(ApplyError, match="not a UTF-8 text file"):
        plan_change(binary, "text")


@pytest.mark.skipif(os.name != "nt", reason="symlink creation needs Windows privileges here")
def test_symlink_escaping_the_workspace_is_refused(tmp_path: Path) -> None:
    outside = tmp_path / "outside.py"
    outside.write_text("x = 1\n", encoding="utf-8")
    workspace = tmp_path / "work"
    workspace.mkdir()
    try:
        (workspace / "link.py").symlink_to(outside)
    except OSError:
        pytest.skip("cannot create symlinks without Developer Mode")
    with pytest.raises(ApplyError, match="outside the workspace"):
        resolve_target(workspace, Path("link.py"))


def test_a_file_changed_after_the_diff_is_not_overwritten(tmp_path: Path) -> None:
    target = tmp_path / "add.py"
    target.write_text("old\n", encoding="utf-8")
    change = plan_change(target, "new\n")
    target.write_text("edited meanwhile\n", encoding="utf-8")

    with pytest.raises(ApplyError, match="changed after the diff"):
        write_change(change, tmp_path / "backups")
    assert target.read_text(encoding="utf-8") == "edited meanwhile\n"


def test_identical_content_needs_no_confirmation(tmp_path: Path) -> None:
    (tmp_path / "add.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    written, output, prompts = _apply(tmp_path, "add.py")
    assert written is None and prompts == [] and "already matches" in output


def test_no_workspace_no_argument_no_code(tmp_path: Path) -> None:
    assert "Choose a workspace first" in _apply(None, "x.py")[1]
    assert "Usage: /apply FILE" in _apply(tmp_path, None)[1]
    assert "no code block" in _apply(tmp_path, "x.py", answer="Just words.")[1]
    assert not (tmp_path / "x.py").exists()


def test_terminal_workspace_then_apply(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    session = TerminalSession(tmp_path / "data" / "index.sqlite3")
    workspace = tmp_path / "project"
    workspace.mkdir()
    session.last_outcomes["chat"] = ChatOutcome(answer=ANSWER, trace=[], sources=[])
    console = _console()
    monkeypatch.setattr(console, "input", lambda prompt, **options: "y")

    _handle_command(console, session, f'/workspace "{workspace}"')
    _handle_command(console, session, "/apply add.py")

    assert session.workspace == workspace.resolve()
    assert (workspace / "add.py").read_text(encoding="utf-8").startswith("def add")
    _handle_command(console, session, "/workspace")
    assert str(workspace.resolve()) in console.export_text()
