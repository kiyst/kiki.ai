from pathlib import Path

import pytest
from pypdf import PdfWriter

from deskai.extraction import ExtractionError, extract_chunks
from deskai.retrieval import TextIndex


def test_index_search_and_remove_stale_file(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    document = corpus / "policy.md"
    document.write_text("# Retry policy\n\nRetry failed requests three times.", encoding="utf-8")
    index = TextIndex(tmp_path / "index.sqlite3")

    receipt = index.index_root(corpus)
    results = index.search("retry")

    assert receipt["indexed"] == 1
    assert len(results) == 1
    assert results[0].path == str(document.resolve())
    assert results[0].location_kind == "line"
    assert results[0].start_location == 1
    assert "lines 1" in results[0].citation

    document.unlink()
    receipt = index.index_root(corpus)
    assert receipt["removed"] == 1
    assert index.search("retry") == []


def test_changed_unreadable_file_drops_cached_evidence(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    document = corpus / "policy.md"
    document.write_text("The obsolete answer is seven.", encoding="utf-8")
    index = TextIndex(tmp_path / "index.sqlite3")
    index.index_root(corpus)
    assert index.search("obsolete")

    document.write_bytes(b"\xff\xfe\x00")
    receipt = index.index_root(corpus)

    assert receipt["failed"] == 1
    assert index.search("obsolete") == []


def test_search_ignores_stop_words_and_prioritizes_matching_filename(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "united_states_constitution.txt").write_text(
        "The Constitution begins: We the people form a more perfect Union.",
        encoding="utf-8",
    )
    (corpus / "commentary.txt").write_text(
        "A long commentary asks what the Constitution means for government.",
        encoding="utf-8",
    )
    index = TextIndex(tmp_path / "index.sqlite3")
    index.index_root(corpus)

    results = index.search("What purposes are in the Constitution preamble?", limit=1)

    assert results[0].path.endswith("united_states_constitution.txt")

