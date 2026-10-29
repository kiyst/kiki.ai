from __future__ import annotations

from pathlib import Path

import pytest
from rich.console import Console

from kiki.finding import FileFinder
from kiki.folders_command import folders_command
from kiki.retrieval import TextIndex
from kiki.terminal import TerminalSession, _handle_command


def _tree(root: Path) -> Path:
    for relative, text in {
        "notes/garden.md": "# Garden plan\n\nTomatoes by the fence.",
        "notes/sub/recipes.txt": "Pierogi dough.",
        "photos/beach.jpg": "",
        ".venv/lib/site.py": "import os",
        "app/node_modules/pkg/index.js": "module.exports = {}",
    }.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root.resolve()


def _run(index: TextIndex, argument: str, *, reply: str = "y",
         browsed: Path | None = None) -> tuple[bool, str]:
    console = Console(record=True, width=160)
    changed = folders_command(console, index, argument, read=lambda prompt: reply,
                              browse=lambda: browsed)
    return changed, " ".join(console.export_text().split())  # ignore line wrapping


def test_tool_folders_are_neither_read_nor_listed(tmp_path: Path) -> None:
    root = _tree(tmp_path / "home")
    index = TextIndex(tmp_path / "index.sqlite3")
    counts = index.index_root(root)

    assert counts["indexed"] == 2 and counts["catalogued"] == 3
    names = {Path(entry["path"]).name for entry in index.catalog_entries()}
    assert names == {"garden.md", "recipes.txt", "beach.jpg"}


def test_add_list_reindex_and_remove(tmp_path: Path) -> None:
    root = _tree(tmp_path / "home")
    index = TextIndex(tmp_path / "index.sqlite3")

    changed, output = _run(index, f'add "{root}"')
    assert changed and "3 files listed for /find" in output and "2 readable (2 new" in output

    _, output = _run(index, "")
    assert str(root) in output and "Indexed folders" in output
    assert index.roots()[0]["files"] == 3 and index.roots()[0]["indexed_at"]

    (root / "notes/new-idea.md").write_text("Kayak trip.", encoding="utf-8")
    (root / "notes/sub/recipes.txt").unlink()
    _, output = _run(index, "reindex 1")
    assert "1 new or changed" in output and "1 gone since last time" in output
    assert FileFinder(index).find("kayak").candidates[0].name == "new-idea.md"

    changed, output = _run(index, "remove 1", reply="n")
    assert not changed and "Kept." in output and index.roots()
    changed, output = _run(index, "remove 1")
    assert changed and "Forgot 3 files" in output
    assert index.roots() == [] and index.catalog_entries() == []
    assert index.health()["chunks"] == 0
    assert (root / "notes/garden.md").exists()  # nothing on disk is touched


def test_browse_and_bad_input(tmp_path: Path) -> None:
    root = _tree(tmp_path / "home")
    index = TextIndex(tmp_path / "index.sqlite3")

    assert _run(index, "add browse", browsed=root)[0]
    assert "No folder added" in _run(index, "add", browsed=None)[1]
    assert "Not a folder" in _run(index, f"add {root / 'missing'}")[1]
    assert "Choose a folder number" in _run(index, "remove 7")[1]
    assert "Usage: /folders" in _run(index, "frobnicate")[1]


def test_nested_folders(tmp_path: Path) -> None:
    root = _tree(tmp_path / "home")
    index = TextIndex(tmp_path / "index.sqlite3")
    index.index_root(root / "notes")

    # A folder inside an indexed one is refused rather than indexed twice.
    _run(index, f"add {root}")
    _, output = _run(index, f"add {root / 'notes' / 'sub'}")
    assert "already inside the indexed folder" in output
    # Adding a parent absorbs the inner folder and keeps its readable files.
    assert [entry["path"] for entry in index.roots()] == [str(root)]
    assert index.roots()[0]["readable"] == 2


def test_cancelling_leaves_the_index_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _tree(tmp_path / "home")
    index = TextIndex(tmp_path / "index.sqlite3")
    original = TextIndex._replace_file

    def interrupted(self, *args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(TextIndex, "_replace_file", interrupted)
    changed, output = _run(index, f"add {root}")
    assert not changed and "Cancelled; nothing changed" in output
    assert index.roots() == [] and index.catalog_entries() == []
    monkeypatch.setattr(TextIndex, "_replace_file", original)


def test_terminal_folders_clears_the_last_find(tmp_path: Path) -> None:
    root = _tree(tmp_path / "home")
    session = TerminalSession(tmp_path / "data" / "index.sqlite3")
    console = Console(record=True, width=160)

    _handle_command(console, session, f"/folders add {root}")
    _handle_command(console, session, "/find garden")
    assert session.last_find is not None
    _handle_command(console, session, "/folders reindex")
    assert session.last_find is None
    _handle_command(console, session, "/folders")
    assert "does not watch these folders yet" in console.export_text()
