from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from rich.console import Console

from kiki.find_evals import run_find_eval
from kiki.finding import FileFinder, FindError, parse_query, query_words
from kiki.retrieval import TextIndex
from kiki.terminal import TerminalSession, _handle_command

NOW = datetime(2026, 10, 29, tzinfo=UTC)


def _write(root: Path, relative: str, content: str | bytes = b"\x00\x01binary",
           when: datetime | None = None) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    if when:
        os.utime(path, (when.timestamp(), when.timestamp()))
    return path


@pytest.fixture
def library(tmp_path: Path) -> tuple[Path, TextIndex]:
    root = tmp_path / "home"
    _write(root, "Documents/Work/Kestrel/Kestrel_Budget_March.xlsx")
    _write(root, "Documents/Work/Kestrel/Kestrel_Budget_April.xlsx")
    _write(root, "Documents/Personal/notes-1.txt",
           "Feed the sourdough starter twice a day.\n\nKeep it warm.")
    _write(root, "Documents/Personal/notes-2.txt", "Groceries and errands for the week.")
    _write(root, "Desktop/untitled.md", "# Passport Renewal Checklist\n\nPhotos, form DS-82.")
    _write(root, "Documents/Taxes/2024/scan_123.pdf", b"not really a pdf")
    _write(root, "Documents/Archive/falcon-report.docx", when=datetime(2023, 5, 1, tzinfo=UTC))
    _write(root, "Documents/Work/falcon-report.docx", when=datetime(2025, 9, 1, tzinfo=UTC))
    _write(root, "app/node_modules/kestrel/kestrel-budget.js", "module.exports = 1")
    _write(root, ".git/objects/kestrel-budget", "x")
    index = TextIndex(tmp_path / "index.sqlite3")
    index.index_root(root)
    return root.resolve(), index


def _find(index: TextIndex, query: str, limit: int = 3):
    return FileFinder(index).find(query, limit, now=NOW)


def test_catalog_covers_unreadable_files_and_skips_tool_folders(library) -> None:
    root, index = library
    paths = {Path(entry["path"]).relative_to(root).as_posix(): entry for entry in index.catalog_entries()}

    assert "Documents/Work/Kestrel/Kestrel_Budget_March.xlsx" in paths
    assert paths["Documents/Work/Kestrel/Kestrel_Budget_March.xlsx"]["searchable"] == 0
    assert paths["Documents/Personal/notes-1.txt"]["searchable"] == 1
    assert not any("node_modules" in path or ".git" in path for path in paths)
    assert index.health()["catalogued_files"] == len(paths)


def test_name_decides_between_similar_files(library) -> None:
    root, index = library
    result = _find(index, "the kestrel budget spreadsheet from march")

    top = result.candidates[0]
    assert top.name == "Kestrel_Budget_March.xlsx" and top.confidence == "Likely"
    assert top.reasons["name"] == ["kestrel", "budget", "march"]
    assert top.reasons["type"] == ["spreadsheet"]
    assert not top.searchable
    assert all("node_modules" not in candidate.path for candidate in result.candidates)


def test_contents_title_and_folder_find_generic_names(library) -> None:
    _, index = library
    assert _find(index, "my notes about sourdough starters").candidates[0].name == "notes-1.txt"
    titled = _find(index, "passport renewal checklist").candidates[0]
    assert titled.name == "untitled.md" and titled.title == "Passport Renewal Checklist"
    scan = _find(index, "2024 taxes scan").candidates[0]
    assert scan.name == "scan_123.pdf" and "folder" in scan.reasons


def test_ambiguous_and_absent_questions_are_not_confident(library) -> None:
    _, index = library
    ambiguous = _find(index, "kestrel budget")
    assert {c.name for c in ambiguous.candidates[:2]} == {
        "Kestrel_Budget_March.xlsx", "Kestrel_Budget_April.xlsx"}
    assert all(c.confidence != "Likely" for c in ambiguous.candidates)
    assert _find(index, "zeppelin harpsichord manual").candidates == []


def test_only_a_clear_leader_is_likely_and_labels_never_rise(tmp_path: Path) -> None:
    # Found on a real folder: a file matched mostly by contents was labelled
    # Likely below two Possible files, and three files were Likely at once.
    root = tmp_path / "docs"
    _write(root, "CODING_SANDBOX_HANDOFF.md", "# Coding sandbox\n\nPlan.")
    _write(root, "PROJECT_HANDOFF.md", "# Kiki project\n\nThe sandbox milestone.")
    _write(root, "notes/sandbox-ideas.md", "Ideas for a handoff later.")
    index = TextIndex(tmp_path / "index.sqlite3")
    index.index_root(root)

    labels = [c.confidence for c in _find(index, "sandbox handoff").candidates]
    assert labels[0] == "Likely" and labels.count("Likely") == 1
    order = ["Weak match", "Possible", "Likely"]
    assert [order.index(label) for label in labels] == sorted(
        (order.index(label) for label in labels), reverse=True)


def test_deleted_files_are_never_returned_and_changes_are_flagged(library) -> None:
    root, index = library
    (root / "Documents/Work/Kestrel/Kestrel_Budget_March.xlsx").unlink()
    (root / "Documents/Personal/notes-1.txt").write_text("Sourdough starter, fed daily now.", encoding="utf-8")

    result = _find(index, "kestrel budget march")
    assert all(not c.path.endswith("Kestrel_Budget_March.xlsx") for c in result.candidates)
    assert result.missing_skipped == 1
    assert _find(index, "sourdough starter").candidates[0].changed_since_indexing


def test_filters(library) -> None:
    _, index = library
    newer = _find(index, "falcon report after:2025")
    assert [c.folder for c in newer.candidates] == [str(Path("Documents/Work"))]
    older = _find(index, "falcon report before:2024")
    assert [c.folder for c in older.candidates] == [str(Path("Documents/Archive"))]
    assert {c.name for c in _find(index, "ext:md", limit=5).candidates} == {"untitled.md"}
    only_filters = _find(index, "in:Taxes", limit=5)
    assert [c.confidence for c in only_filters.candidates] == ["Matches filters"]
    assert _find(index, "budget name:april").candidates[0].name == "Kestrel_Budget_April.xlsx"
    assert _find(index, "kestrel larger:1GB").candidates == []


def test_query_parsing() -> None:
    words, filters = parse_query("budget ext:xlsx,.csv in:Work after:7d smaller:2.5MB", now=NOW)
    assert words == "budget"
    assert filters.extensions == {".xlsx", ".csv"} and filters.folder == "Work"
    assert filters.after_ns == int(datetime(2026, 10, 22, tzinfo=UTC).timestamp() * 1e9)
    assert filters.smaller == int(2.5 * 1024**2)
    assert query_words("Where's the file I can't find about my taxes?") == ["taxes"]
    with pytest.raises(FindError, match="date"):
        parse_query("after:yesterday")
    with pytest.raises(FindError, match="size"):
        parse_query("larger:huge")
    with pytest.raises(FindError, match="Describe the file"):
        FileFinder.__new__(FileFinder).find("the file")


def test_schema_4_index_is_backfilled(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    _write(root, "garden.md", "# Garden\n\nTomatoes.")
    database = tmp_path / "index.sqlite3"
    TextIndex(database).index_root(root)
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE catalog")
        connection.execute("PRAGMA user_version = 4")
    connection.close()

    index = TextIndex(database)
    assert [entry["name"] for entry in index.catalog_entries()] == ["garden.md"]
    assert _find(index, "garden").candidates[0].confidence == "Likely"


def test_terminal_find_keeps_the_last_list(library, tmp_path: Path) -> None:
    _, index = library
    session = TerminalSession(index.database)
    console = Console(record=True, width=160)

    _handle_command(console, session, "/find kestrel budget march")
    assert session.last_find is not None
    assert session.last_find.candidates[0].name == "Kestrel_Budget_March.xlsx"
    _handle_command(console, session, "/find")
    _handle_command(console, session, "/find after:someday")
    output = console.export_text()
    assert output.count("1. Kestrel_Budget_March.xlsx") == 2
    assert session.last_find.candidates[0].path in output
    assert "Contents not readable by Kiki" in output
    assert "Could not read the date" in output


def test_generated_folder_evaluation_invariants() -> None:
    report = run_find_eval((7,))
    assert report["stale_returned"] == 0
    assert report["dependency_returned"] == 0
    assert report["invalid_paths"] == 0
    assert report["absent_with_likely"] == 0
    assert report["recall@3"] >= 0.9
