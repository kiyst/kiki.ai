from __future__ import annotations

import hashlib
import gc
import json
import os
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import sleep
from collections.abc import Callable, Collection
from typing import Any, Iterator

from .extraction import (
    extraction_version,
    SUPPORTED_EXTENSIONS,
    ExtractedChunk,
    ExtractionError,
    document_title,
    extract_chunks,
)
from .resilience import KikiError, ErrorCode


@dataclass(frozen=True)
class SearchResult:
    source_id: str
    path: str
    location_kind: str
    start_location: int
    end_location: int
    excerpt: str
    score: float
    title: str | None = None
    # Which stage produced `score` (e.g. "fused", "grader:qwen3:4b-instruct");
    # scores from different stages are on different scales.
    ranker: str | None = None

    @property
    def passage_id(self) -> str:
        """Stable ID of this passage: the same file content and span always map
        to the same ID, and an edited or re-extracted file gets new ones."""
        return passage_identifier(
            self.source_id, self.location_kind, self.start_location, self.end_location
        )

    @property
    def location_label(self) -> str:
        return location_label(self.location_kind, self.start_location, self.end_location)

    @property
    def citation(self) -> str:
        return f"[source:{self.passage_id}] {self.path} ({self.location_label})"

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "passage_id": self.passage_id, "citation": self.citation}


def location_label(kind: str, start: int, end: int) -> str:
    """"page 4", "pages 4-5", "paragraphs 12-18", or "lines 10-22"."""
    if kind in {"page", "paragraph"}:
        label = kind if end == start else f"{kind}s"
    else:
        label = "lines"
    return f"{label} {start}" + (f"-{end}" if end != start else "")


def passage_identifier(source_id: str, location_kind: str, start: int, end: int) -> str:
    """Derived from stored fields, so existing indexes need no migration."""
    digest = hashlib.sha256(f"{source_id}\0{location_kind}\0{start}\0{end}".encode()).hexdigest()
    return f"p{digest[:11]}"


@dataclass(frozen=True)
class ChunkForEmbedding:
    chunk_id: int
    text: str


class TextIndex:
    """Authoritative manifest plus SQLite FTS retrieval for selected roots."""

    SCHEMA_VERSION = 5
    MAX_FILE_BYTES = 25 * 1024 * 1024
    MAX_CATALOG_FILES = 200_000
    # Tool and dependency folders that only bury the user's own files.
    CATALOG_SKIP_DIRS = frozenset({
        ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
        ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".cache",
        "$recycle.bin", "system volume information",
    })

    def __init__(self, database: Path) -> None:
        self.database = database.resolve()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.recovery_notice: str | None = None
        try:
            self._initialize()
        except sqlite3.DatabaseError as exc:
            self._recover_corrupt_database(exc)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            try:
                with connection:
                    yield connection
            except sqlite3.OperationalError as exc:
                retryable = "locked" in str(exc).casefold() or "busy" in str(exc).casefold()
                raise KikiError(
                    "The document index is busy; try again shortly"
                    if retryable
                    else "The document index could not complete the operation",
                    code=ErrorCode.INDEX_UNAVAILABLE,
                    retryable=retryable,
                ) from exc
        finally:
            connection.close()

    @property
    def roots_manifest(self) -> Path:
        return self.database.with_suffix(self.database.suffix + ".roots.json")

    def _record_roots(self) -> None:
        with self._session() as connection:
            roots = [row["path"] for row in connection.execute("SELECT path FROM roots ORDER BY path")]
        self.roots_manifest.write_text(json.dumps(roots, indent=2), encoding="utf-8")

    def backup(self) -> Path:
        destination = self.database.with_suffix(self.database.suffix + ".backup")
        source = self._connect()
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        return destination

    def health(self) -> dict[str, object]:
        try:
            with self._session() as connection:
                result = connection.execute("PRAGMA quick_check").fetchone()[0]
                files = connection.execute("SELECT COUNT(*) FROM files").fetchone()[0]
                chunks = connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
                catalogued = connection.execute("SELECT COUNT(*) FROM catalog").fetchone()[0]
            return {
                "status": "ok" if result == "ok" else "degraded",
                "integrity": result,
                "files": int(files),
                "chunks": int(chunks),
                "catalogued_files": int(catalogued),
                "recovery_notice": self.recovery_notice,
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def _recover_corrupt_database(self, cause: sqlite3.DatabaseError) -> None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        quarantined = self.database.with_suffix(self.database.suffix + f".corrupt-{stamp}")
        roots: list[str] = []
        if self.roots_manifest.is_file():
            try:
                loaded = json.loads(self.roots_manifest.read_text(encoding="utf-8"))
                roots = [value for value in loaded if isinstance(value, str)]
            except (OSError, ValueError, TypeError):
                roots = []
        if self.database.exists():
            gc.collect()
            moved = False
            for attempt in range(3):
                try:
                    self.database.replace(quarantined)
                    moved = True
                    break
                except PermissionError:
                    if attempt < 2:
                        sleep(0.05)
            if not moved:
                # Some Windows SQLite builds briefly retain the bad file handle.
                # Preserve it in place and recover to an adjacent active database.
                quarantined = self.database
                self.database = self.database.with_suffix(
                    self.database.suffix + f".recovered-{stamp}"
                )
        self._initialize()
        self.recovery_notice = (
            f"Recovered a corrupt index ({cause}); preserved it at {quarantined}"
        )
        for root in roots:
            path = Path(root)
            if path.is_dir():
                self.index_root(path)

    def _initialize(self) -> None:
        with self._session() as connection:
            current = connection.execute("PRAGMA user_version").fetchone()[0]
            existing = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='files'"
            ).fetchone()
            if existing and current not in (2, 3, 4, self.SCHEMA_VERSION):
                raise RuntimeError(
                    f"Index schema {current} is incompatible with {self.SCHEMA_VERSION}; delete and reindex"
                )
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS roots (path TEXT PRIMARY KEY, indexed_at TEXT);
                CREATE TABLE IF NOT EXISTS files (
                    source_id TEXT PRIMARY KEY,
                    root TEXT NOT NULL,
                    path TEXT UNIQUE NOT NULL,
                    content_hash TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    modified_ns INTEGER NOT NULL,
                    title TEXT
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY,
                    source_id TEXT NOT NULL REFERENCES files(source_id) ON DELETE CASCADE,
                    location_kind TEXT NOT NULL,
                    start_location INTEGER NOT NULL,
                    end_location INTEGER NOT NULL,
                    content TEXT NOT NULL
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                    content,
                    path UNINDEXED,
                    source_id UNINDEXED,
                    location_kind UNINDEXED,
                    start_location UNINDEXED,
                    end_location UNINDEXED,
                    tokenize = 'porter unicode61'
                );
                CREATE TABLE IF NOT EXISTS chunk_embeddings (
                    chunk_id INTEGER PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
                    model TEXT NOT NULL,
                    dimensions INTEGER NOT NULL,
                    vector BLOB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS catalog (
                    path TEXT PRIMARY KEY,
                    root TEXT NOT NULL,
                    name TEXT NOT NULL,
                    extension TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    modified_ns INTEGER NOT NULL,
                    searchable INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS catalog_root ON catalog(root);
                """
            )
            if existing and current < 4:
                self._rebuild_stemmed_fts(connection)
            if existing and current < 5:
                # Schema 5 catalogs every file for /find. Until the next
                # `kiki index`, an older index knows only its readable files.
                connection.executemany(
                    "INSERT OR IGNORE INTO catalog VALUES (?, ?, ?, ?, ?, ?, 1)",
                    [
                        (row["path"], row["root"], Path(row["path"]).name,
                         Path(row["path"]).suffix.casefold(), row["size"], row["modified_ns"])
                        for row in connection.execute(
                            "SELECT path, root, size, modified_ns FROM files"
                        ).fetchall()
                    ],
                )
            if "indexed_at" not in {
                row["name"] for row in connection.execute("PRAGMA table_info(roots)")
            }:
                connection.execute("ALTER TABLE roots ADD COLUMN indexed_at TEXT")
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(files)")}
            if "title" not in columns:
                # Titles let citations and queries refer to "the Beard history"
                # instead of a filename; backfill from files still on disk.
                connection.execute("ALTER TABLE files ADD COLUMN title TEXT")
                for row in connection.execute("SELECT source_id, path FROM files").fetchall():
                    connection.execute(
                        "UPDATE files SET title = ? WHERE source_id = ?",
                        (document_title(Path(row["path"])), row["source_id"]),
                    )
            connection.execute(f"PRAGMA user_version = {self.SCHEMA_VERSION}")

    @staticmethod
    def _rebuild_stemmed_fts(connection: sqlite3.Connection) -> None:
        """Schema 4 stems terms so "borrowing" matches "borrow"; rebuild in place."""
        connection.execute("DROP TABLE IF EXISTS chunks_fts")
        connection.execute(
            """
            CREATE VIRTUAL TABLE chunks_fts USING fts5(
                content,
                path UNINDEXED,
                source_id UNINDEXED,
                location_kind UNINDEXED,
                start_location UNINDEXED,
                end_location UNINDEXED,
                tokenize = 'porter unicode61'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO chunks_fts(content, path, source_id, location_kind, start_location, end_location)
            SELECT c.content, f.path, c.source_id, c.location_kind, c.start_location, c.end_location
            FROM chunks AS c JOIN files AS f ON f.source_id = c.source_id
            ORDER BY c.id
            """
        )

    def index_root(
        self, root: Path, progress: Callable[[int, int], None] | None = None
    ) -> dict[str, object]:
        """Read and catalogue a folder; `progress(done, total)` reports readable files."""
        root = root.resolve(strict=True)
        if not root.is_dir():
            raise ValueError(f"Not a directory: {root}")

        counts = {"indexed": 0, "unchanged": 0, "skipped": 0, "failed": 0, "removed": 0}
        issues: list[dict[str, str]] = []
        seen: set[str] = set()
        files = self._walk(root, issues)
        readable = [(path, size) for path, size, _ in files if path.suffix.lower() in SUPPORTED_EXTENSIONS]
        counts["skipped"] = len(files) - len(readable)
        with self._session() as connection:
            self._claim_root(connection, root)
            for done, (path, size) in enumerate(readable, start=1):
                if progress:
                    progress(done, len(readable))
                if size > self.MAX_FILE_BYTES:
                    counts["skipped"] += 1
                    issues.append({"path": str(path), "reason": "file exceeds 25 MiB limit"})
                    continue
                seen.add(str(path))
                try:
                    changed = self._replace_file(connection, root, path)
                except (ExtractionError, OSError) as exc:
                    self._delete_path(connection, path)
                    seen.discard(str(path))
                    counts["failed"] += 1
                    issues.append({"path": str(path), "reason": str(exc)})
                    continue
                counts["indexed" if changed else "unchanged"] += 1

            current = connection.execute(
                "SELECT source_id, path FROM files WHERE root = ?", (str(root),)
            ).fetchall()
            stale = [row for row in current if row["path"] not in seen]
            for row in stale:
                self._delete_source(connection, row["source_id"])
            counts["removed"] = len(stale)
            connection.execute("DELETE FROM catalog WHERE root = ?", (str(root),))
            connection.executemany(
                "INSERT OR REPLACE INTO catalog VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (str(path), str(root), path.name, path.suffix.casefold(), size,
                     modified_ns, int(str(path) in seen))
                    for path, size, modified_ns in files
                ],
            )
            counts["catalogued"] = len(files)
            connection.execute(
                "UPDATE roots SET indexed_at = ? WHERE path = ?",
                (datetime.now(UTC).isoformat(timespec="seconds"), str(root)),
            )
        self._record_roots()
        self.backup()
        return {**counts, "issues": issues}

    def _walk(self, root: Path, issues: list[dict[str, str]]) -> list[tuple[Path, int, int]]:
        """Every file under the root as (path, size, modified_ns), skipping tool
        folders and links (which could lead outside the root)."""
        files: list[tuple[Path, int, int]] = []
        for folder, subfolders, names in os.walk(root, onerror=lambda error: None):
            subfolders[:] = sorted(
                name for name in subfolders
                if name.casefold() not in self.CATALOG_SKIP_DIRS
                and not _is_link(os.path.join(folder, name))
            )
            for name in sorted(names):
                path = Path(folder, name)
                try:
                    if path.is_symlink():
                        continue
                    stat = path.stat()
                except OSError:
                    continue
                files.append((path, stat.st_size, stat.st_mtime_ns))
            if len(files) >= self.MAX_CATALOG_FILES:
                issues.append({
                    "path": str(root),
                    "reason": f"stopped at {self.MAX_CATALOG_FILES:,} files",
                })
                break
        return files

    def _claim_root(self, connection: sqlite3.Connection, root: Path) -> None:
        """Register a root. A folder already inside an indexed folder is refused;
        indexed folders inside this one are absorbed, keeping their files."""
        for row in connection.execute("SELECT path FROM roots").fetchall():
            existing = Path(row["path"])
            if existing != root and root.is_relative_to(existing):
                raise ValueError(
                    f"{root} is already inside the indexed folder {existing}; "
                    "reindex that folder instead"
                )
            if existing != root and existing.is_relative_to(root):
                for table in ("files", "catalog"):
                    connection.execute(
                        f"UPDATE {table} SET root = ? WHERE root = ?", (str(root), str(existing))
                    )
                connection.execute("DELETE FROM roots WHERE path = ?", (str(existing),))
        connection.execute("INSERT OR IGNORE INTO roots(path) VALUES (?)", (str(root),))

    def roots(self) -> list[dict[str, Any]]:
        """Indexed folders with their file counts and when they were last indexed."""
        with self._session() as connection:
            rows = connection.execute(
                """
                SELECT r.path, r.indexed_at,
                       (SELECT COUNT(*) FROM catalog AS c WHERE c.root = r.path) AS files,
                       (SELECT COUNT(*) FROM files AS f WHERE f.root = r.path) AS readable
                FROM roots AS r ORDER BY r.path
                """
            ).fetchall()
        return [{**dict(row), "exists": Path(row["path"]).is_dir()} for row in rows]

    def remove_root(self, root: Path) -> int:
        """Forget a folder: its passages, embeddings, and catalog entries. The
        folder and its files on disk are not touched. Returns files forgotten."""
        key = str(root)
        with self._session() as connection:
            if not connection.execute("SELECT 1 FROM roots WHERE path = ?", (key,)).fetchone():
                raise ValueError(f"Not an indexed folder: {root}")
            forgotten = connection.execute(
                "SELECT COUNT(*) FROM catalog WHERE root = ?", (key,)
            ).fetchone()[0]
            for row in connection.execute(
                "SELECT source_id FROM files WHERE root = ?", (key,)
            ).fetchall():
                self._delete_source(connection, row["source_id"])
            connection.execute("DELETE FROM catalog WHERE root = ?", (key,))
            connection.execute("DELETE FROM roots WHERE path = ?", (key,))
        self._record_roots()
        return int(forgotten)

    def catalog_entries(self) -> list[dict[str, Any]]:
        """Every catalogued file, with its title when its contents were read."""
        with self._session() as connection:
            rows = connection.execute(
                """
                SELECT c.path, c.root, c.name, c.extension, c.size, c.modified_ns,
                       c.searchable, f.title, f.source_id
                FROM catalog AS c LEFT JOIN files AS f ON f.path = c.path
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def content_matches(self, terms: list[str], limit: int = 20_000) -> dict[str, dict[str, float]]:
        """For each term, the paths whose extracted text contains it and their
        best BM25 relevance (higher is better). Terms are stemmed like search."""
        matches: dict[str, dict[str, float]] = {}
        with self._session() as connection:
            for term in terms:
                best: dict[str, float] = {}
                for row in connection.execute(
                    "SELECT path, bm25(chunks_fts) AS rank FROM chunks_fts "
                    "WHERE chunks_fts MATCH ? LIMIT ?",
                    (f'"{term}"', limit),
                ):
                    best[row["path"]] = max(best.get(row["path"], 0.0), -float(row["rank"]))
                matches[term] = best
        return matches

    def _replace_file(self, connection: sqlite3.Connection, root: Path, path: Path) -> bool:
        data = path.read_bytes()
        version = extraction_version(path).encode("ascii")
        digest = hashlib.sha256(data + b"\0" + version).hexdigest()
        existing = connection.execute(
            "SELECT source_id, content_hash FROM files WHERE path = ?", (str(path),)
        ).fetchone()
        if existing and existing["content_hash"] == digest:
            return False

        chunks = extract_chunks(path)
        source_id = hashlib.sha256(f"{path}\0{digest}".encode("utf-8")).hexdigest()[:16]
        if existing:
            self._delete_source(connection, existing["source_id"])
        stat = path.stat()
        connection.execute(
            "INSERT INTO files(source_id, root, path, content_hash, size, modified_ns, title) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                source_id,
                str(root),
                str(path),
                digest,
                stat.st_size,
                stat.st_mtime_ns,
                document_title(path),
            ),
        )
        for chunk in chunks:
            self._insert_chunk(connection, path, source_id, chunk)
        return True

    def _insert_chunk(
        self, connection: sqlite3.Connection, path: Path, source_id: str, chunk: ExtractedChunk
    ) -> None:
        connection.execute(
            "INSERT INTO chunks(source_id, location_kind, start_location, end_location, content) VALUES (?, ?, ?, ?, ?)",
            (source_id, chunk.location_kind, chunk.start_location, chunk.end_location, chunk.text),
        )
        connection.execute(
            "INSERT INTO chunks_fts(content, path, source_id, location_kind, start_location, end_location) VALUES (?, ?, ?, ?, ?, ?)",
            (
                chunk.text,
                str(path),
                source_id,
                chunk.location_kind,
                chunk.start_location,
                chunk.end_location,
            ),
        )

    def _delete_source(self, connection: sqlite3.Connection, source_id: str) -> None:
        connection.execute("DELETE FROM chunks_fts WHERE source_id = ?", (source_id,))
        connection.execute("DELETE FROM files WHERE source_id = ?", (source_id,))

    def _delete_path(self, connection: sqlite3.Connection, path: Path) -> None:
        existing = connection.execute(
            "SELECT source_id FROM files WHERE path = ?", (str(path),)
        ).fetchone()
        if existing:
            self._delete_source(connection, existing["source_id"])

    def search(
        self, query: str, limit: int = 5, source_ids: Collection[str] | None = None
    ) -> list[SearchResult]:
        query = query.strip()
        if not query:
            raise ValueError("Query must not be empty")
        if not 1 <= limit <= 100:
            raise ValueError("Limit must be between 1 and 100")
        tokens = _query_tokens(query)
        if not tokens:
            raise ValueError("Query has no searchable terms")
        fts_query = " OR ".join(f'"{token}"' for token in tokens)
        # Unchanged for limit <= 20 (the historical setting); larger pools for
        # candidate experiments get a proportionally larger BM25 window.
        candidate_limit = min(max(100, limit * 2), max(limit * 10, 20))
        with self._session() as connection:
            if source_ids is None:
                rows = self._fts_rows(connection, fts_query, candidate_limit)
                # Large documents can fill the whole BM25 candidate pool; make sure a
                # document the user names by title still contributes candidates.
                named = self._named_sources(connection, query)
                seen = {(row["source_id"], row["start_location"]) for row in rows}
                for row in self._fts_rows(connection, fts_query, limit, named):
                    if (row["source_id"], row["start_location"]) not in seen:
                        rows.append(row)
            else:
                rows = self._fts_rows(connection, fts_query, candidate_limit, source_ids)
            titles = dict(connection.execute("SELECT source_id, title FROM files").fetchall())
        rows = sorted(rows, key=lambda row: _lexical_rank(row, tokens), reverse=True)[:limit]
        return [
            SearchResult(
                source_id=row["source_id"],
                path=row["path"],
                location_kind=row["location_kind"],
                start_location=int(row["start_location"]),
                end_location=int(row["end_location"]),
                excerpt=row["content"],
                score=float(-row["rank"]) + 100.0 * _filename_hits(row["path"], tokens),
                title=titles.get(row["source_id"]),
            )
            for row in rows
            if Path(row["path"]).is_file()
        ]

    @staticmethod
    def _fts_rows(
        connection: sqlite3.Connection,
        fts_query: str,
        limit: int,
        source_ids: Collection[str] | None = None,
    ) -> list[sqlite3.Row]:
        restriction = ""
        parameters: list[object] = [fts_query]
        if source_ids is not None:
            if not source_ids:
                return []
            restriction = f" AND source_id IN ({', '.join('?' for _ in source_ids)})"
            parameters.extend(source_ids)
        parameters.append(limit)
        return connection.execute(
            f"""
            SELECT source_id, path, location_kind, start_location, end_location,
                   content, bm25(chunks_fts) AS rank
            FROM chunks_fts WHERE chunks_fts MATCH ?{restriction} ORDER BY rank LIMIT ?
            """,
            parameters,
        ).fetchall()

    def named_sources(self, query: str) -> list[str]:
        """Source IDs of indexed documents that the query refers to by title."""
        with self._session() as connection:
            return self._named_sources(connection, query)

    @staticmethod
    def _named_sources(connection: sqlite3.Connection, query: str) -> list[str]:
        files = connection.execute("SELECT source_id, path, title FROM files").fetchall()
        return _named_sources(
            query, [(row["source_id"], row["path"], row["title"]) for row in files]
        )

    def chunks_needing_embeddings(self, model: str, limit: int) -> list[ChunkForEmbedding]:
        with self._session() as connection:
            rows = connection.execute(
                """
                SELECT c.id, c.content
                FROM chunks AS c
                LEFT JOIN chunk_embeddings AS e ON e.chunk_id = c.id AND e.model = ?
                WHERE e.chunk_id IS NULL
                ORDER BY c.id
                LIMIT ?
                """,
                (model, limit),
            ).fetchall()
        return [ChunkForEmbedding(int(row["id"]), row["content"]) for row in rows]

    def save_embeddings(
        self, model: str, embeddings: list[tuple[int, int, bytes]]
    ) -> None:
        with self._session() as connection:
            connection.executemany(
                """
                INSERT INTO chunk_embeddings(chunk_id, model, dimensions, vector)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(chunk_id) DO UPDATE SET
                    model = excluded.model,
                    dimensions = excluded.dimensions,
                    vector = excluded.vector
                """,
                [(chunk_id, model, dimensions, vector) for chunk_id, dimensions, vector in embeddings],
            )

    def embedding_rows(self, model: str) -> list[sqlite3.Row]:
        with self._session() as connection:
            return connection.execute(
                """
                SELECT e.dimensions, e.vector, f.source_id, f.path, f.title,
                       c.location_kind, c.start_location, c.end_location, c.content
                FROM chunk_embeddings AS e
                JOIN chunks AS c ON c.id = e.chunk_id
                JOIN files AS f ON f.source_id = c.source_id
                WHERE e.model = ?
                """,
                (model,),
            ).fetchall()

    def embedding_count(self, model: str) -> int:
        with self._session() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM chunk_embeddings WHERE model = ?", (model,)
            ).fetchone()
        return int(row["count"])


_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "did", "do", "does",
    "for", "from", "had", "has", "have", "how", "in", "into", "is", "it",
    "its", "of", "on", "or", "that", "the", "their", "this", "to", "was",
    "were", "what", "when", "where", "which", "who", "why", "with", "would",
}


def _is_link(path: str) -> bool:
    """Symlinks and Windows junctions, which could lead outside the root."""
    return os.path.islink(path) or getattr(os.path, "isjunction", lambda _: False)(path)


def _query_tokens(query: str) -> list[str]:
    raw = [token.casefold() for token in re.findall(r"[\w]+", query, flags=re.UNICODE)]
    useful = [token for token in raw if len(token) > 1 and token not in _STOP_WORDS]
    selected = useful or [token for token in raw if len(token) > 1]
    return list(dict.fromkeys(selected))


def _filename_hits(path: str, tokens: list[str]) -> int:
    filename = Path(path).stem.casefold().replace("_", " ").replace("-", " ")
    return sum(token in filename for token in tokens)


def _title_words(path: str) -> list[str]:
    stem = Path(path).stem.casefold()
    return [word for word in re.split(r"[\W_]+", stem) if word]


def _author_surnames(title: str | None) -> list[str]:
    if not title or " by " not in title:
        return []
    authors = title.rsplit(" by ", 1)[1]
    return [
        words[-1]
        for author in authors.split(" and ")
        if (words := re.findall(r"\w+", author.casefold()))
    ]


def _named_sources(
    query: str, files: list[tuple[str, str] | tuple[str, str, str | None]]
) -> list[str]:
    """Match a query to documents it names, e.g. "the Declaration" or "Paine".

    A document counts as named when the query contains its whole filename
    phrase ("common sense"), a long filename word no other file shares
    ("constitution"), or an author surname that no other document's author or
    title uses ("Beard"). Shared or short words such as "states" or "common"
    alone are too ambiguous to imply a specific document.
    """
    query_words = re.findall(r"\w+", query.casefold())
    query_text = " ".join(query_words)
    entries = [(item[0], item[1], item[2] if len(item) > 2 else None) for item in files]
    names = {source_id: _title_words(path) for source_id, path, _ in entries}
    surnames = {source_id: _author_surnames(title) for source_id, _, title in entries}
    title_words = {
        word
        for _, _, title in entries
        if title
        for word in re.findall(r"\w+", title.rsplit(" by ", 1)[0].casefold())
    }
    counts: dict[str, int] = {}
    for words in [*names.values(), *surnames.values()]:
        for word in set(words):
            counts[word] = counts.get(word, 0) + 1
    named: list[str] = []
    for source_id, words in names.items():
        meaningful = [word for word in words if word not in _STOP_WORDS]
        if not meaningful:
            continue
        phrase = " ".join(words)
        distinctive = [word for word in meaningful if len(word) >= 8 and counts[word] == 1]
        authors = [
            word
            for word in surnames[source_id]
            if len(word) >= 4 and counts[word] == 1 and word not in title_words
        ]
        if (len(words) > 1 and f" {phrase} " in f" {query_text} ") or any(
            word in query_words for word in [*distinctive, *authors]
        ):
            named.append(source_id)
    return named


def _lexical_rank(row: sqlite3.Row, tokens: list[str]) -> tuple[int, float]:
    return _filename_hits(row["path"], tokens), float(-row["rank"])

