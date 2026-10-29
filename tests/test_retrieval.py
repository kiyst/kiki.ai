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


def test_index_writes_recovery_manifest_and_backup(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "notes.md").write_text("Reliable evidence.", encoding="utf-8")
    index = TextIndex(tmp_path / "index.sqlite3")

    index.index_root(corpus)

    assert index.roots_manifest.is_file()
    assert index.database.with_suffix(".sqlite3.backup").is_file()
    assert index.health()["integrity"] == "ok"


def test_corrupt_index_is_quarantined_and_recreated(tmp_path: Path) -> None:
    database = tmp_path / "index.sqlite3"
    database.write_bytes(b"definitely not sqlite")

    index = TextIndex(database)

    assert index.health()["status"] == "ok"
    assert index.recovery_notice is not None
    assert database.is_file()
    assert index.database != database or list(tmp_path.glob("index.sqlite3.corrupt-*"))



def test_search_stems_terms_and_migrates_unstemmed_index(tmp_path: Path) -> None:
    import sqlite3

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "charter.txt").write_text("Congress may borrow Money on credit.", encoding="utf-8")
    database = tmp_path / "index.sqlite3"
    TextIndex(database).index_root(corpus)

    # Recreate the schema-3 layout: identical rows, but no stemming tokenizer.
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        DROP TABLE chunks_fts;
        CREATE VIRTUAL TABLE chunks_fts USING fts5(
            content, path UNINDEXED, source_id UNINDEXED, location_kind UNINDEXED,
            start_location UNINDEXED, end_location UNINDEXED
        );
        INSERT INTO chunks_fts(content, path, source_id, location_kind, start_location, end_location)
        SELECT c.content, f.path, c.source_id, c.location_kind, c.start_location, c.end_location
        FROM chunks AS c JOIN files AS f USING (source_id);
        PRAGMA user_version = 3;
        """
    )
    unstemmed = connection.execute(
        "SELECT count(*) FROM chunks_fts WHERE chunks_fts MATCH 'borrowing'"
    ).fetchone()[0]
    connection.close()
    assert unstemmed == 0

    results = TextIndex(database).search("Who handles borrowing?")

    assert [Path(result.path).name for result in results] == ["charter.txt"]


def test_titles_are_backfilled_and_author_surnames_name_documents(tmp_path: Path) -> None:
    import sqlite3

    from deskai.retrieval import _named_sources

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "history.txt").write_text(
        "Title: History of the United States\n\nAuthor: Charles A. Beard\n\n"
        "*** START OF THE PROJECT GUTENBERG EBOOK HISTORY ***\n\nThe colonies resisted taxes.\n",
        encoding="utf-8",
    )
    database = tmp_path / "index.sqlite3"
    TextIndex(database).index_root(corpus)
    connection = sqlite3.connect(database)
    connection.execute("ALTER TABLE files DROP COLUMN title")
    connection.commit()
    connection.close()

    index = TextIndex(database)
    result = index.search("colonies taxes")[0]

    assert result.title == "History of the United States by Charles A. Beard"
    assert index.named_sources("What does the Beard history say?") == [result.source_id]
    files = [("a", "us_constitution.txt", "The United States Constitution by United States")]
    assert _named_sources("Where do the states get power?", files) == []
