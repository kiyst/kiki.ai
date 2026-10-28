from __future__ import annotations

import hashlib
import gc
import json
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import sleep
from typing import Iterator

from .extraction import (
    EXTRACTION_VERSION,
    SUPPORTED_EXTENSIONS,
    ExtractedChunk,
    ExtractionError,
    extract_chunks,
)
from .resilience import DeskAIError, ErrorCode


@dataclass(frozen=True)
class SearchResult:
    source_id: str
    path: str
    location_kind: str
    start_location: int
    end_location: int
    excerpt: str
    score: float

    @property
    def citation(self) -> str:
        label = "p." if self.location_kind == "page" else "lines "
        location = str(self.start_location)
        if self.end_location != self.start_location:
            location += f"-{self.end_location}"
        return f"[source:{self.source_id}] {self.path} ({label}{location})"

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "citation": self.citation}


@dataclass(frozen=True)
class ChunkForEmbedding:
    chunk_id: int
    text: str


class TextIndex:
    """Authoritative manifest plus SQLite FTS retrieval for selected roots."""

    SCHEMA_VERSION = 3
    MAX_FILE_BYTES = 25 * 1024 * 1024

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
                raise DeskAIError(
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
            return {
                "status": "ok" if result == "ok" else "degraded",
                "integrity": result,
                "files": int(files),
                "chunks": int(chunks),
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
            if existing and current not in (2, self.SCHEMA_VERSION):
                raise RuntimeError(
                    f"Index schema {current} is incompatible with {self.SCHEMA_VERSION}; delete and reindex"
                )
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS roots (path TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS files (
                    source_id TEXT PRIMARY KEY,
                    root TEXT NOT NULL,
                    path TEXT UNIQUE NOT NULL,
                    content_hash TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    modified_ns INTEGER NOT NULL
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
                    end_location UNINDEXED
                );
                CREATE TABLE IF NOT EXISTS chunk_embeddings (
                    chunk_id INTEGER PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
                    model TEXT NOT NULL,
                    dimensions INTEGER NOT NULL,
                    vector BLOB NOT NULL
                );
                """
            )
            connection.execute(f"PRAGMA user_version = {self.SCHEMA_VERSION}")

    def index_root(self, root: Path) -> dict[str, object]:
        root = root.resolve(strict=True)
        if not root.is_dir():
            raise ValueError(f"Not a directory: {root}")

        counts = {"indexed": 0, "unchanged": 0, "skipped": 0, "failed": 0, "removed": 0}
        issues: list[dict[str, str]] = []
        seen: set[str] = set()
        with self._session() as connection:
            connection.execute("INSERT OR IGNORE INTO roots(path) VALUES (?)", (str(root),))
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                    counts["skipped"] += 1
                    continue
                if path.stat().st_size > self.MAX_FILE_BYTES:
                    counts["skipped"] += 1
                    issues.append({"path": str(path), "reason": "file exceeds 25 MiB limit"})
                    continue
                canonical = path.resolve(strict=True)
                if not canonical.is_relative_to(root):
                    counts["skipped"] += 1
                    issues.append({"path": str(path), "reason": "resolved path is outside selected root"})
                    continue
                seen.add(str(canonical))
                try:
                    changed = self._replace_file(connection, root, canonical)
                except (ExtractionError, OSError) as exc:
                    self._delete_path(connection, canonical)
                    counts["failed"] += 1
                    issues.append({"path": str(canonical), "reason": str(exc)})
                    continue
                counts["indexed" if changed else "unchanged"] += 1

            current = connection.execute(
                "SELECT source_id, path FROM files WHERE root = ?", (str(root),)
            ).fetchall()
            stale = [row for row in current if row["path"] not in seen]
            for row in stale:
                self._delete_source(connection, row["source_id"])
            counts["removed"] = len(stale)
        self._record_roots()
        self.backup()
        return {**counts, "issues": issues}

    def _replace_file(self, connection: sqlite3.Connection, root: Path, path: Path) -> bool:
        data = path.read_bytes()
        digest = hashlib.sha256(data + b"\0" + EXTRACTION_VERSION.encode("ascii")).hexdigest()
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
            "INSERT INTO files VALUES (?, ?, ?, ?, ?, ?)",
            (source_id, str(root), str(path), digest, stat.st_size, stat.st_mtime_ns),
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

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        query = query.strip()
        if not query:
            raise ValueError("Query must not be empty")
        if not 1 <= limit <= 20:
            raise ValueError("Limit must be between 1 and 20")
        tokens = _query_tokens(query)
        if not tokens:
            raise ValueError("Query has no searchable terms")
        fts_query = " OR ".join(f'"{token}"' for token in tokens)
        candidate_limit = min(100, max(limit * 10, 20))
        with self._session() as connection:
            rows = connection.execute(
                """
                SELECT source_id, path, location_kind, start_location, end_location,
                       content, bm25(chunks_fts) AS rank
                FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY rank LIMIT ?
                """,
                (fts_query, candidate_limit),
            ).fetchall()
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
            )
            for row in rows
            if Path(row["path"]).is_file()
        ]

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
                SELECT e.dimensions, e.vector, f.source_id, f.path,
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


def _query_tokens(query: str) -> list[str]:
    raw = [token.casefold() for token in re.findall(r"[\w]+", query, flags=re.UNICODE)]
    useful = [token for token in raw if len(token) > 1 and token not in _STOP_WORDS]
    selected = useful or [token for token in raw if len(token) > 1]
    return list(dict.fromkeys(selected))


def _filename_hits(path: str, tokens: list[str]) -> int:
    filename = Path(path).stem.casefold().replace("_", " ").replace("-", " ")
    return sum(token in filename for token in tokens)


def _lexical_rank(row: sqlite3.Row, tokens: list[str]) -> tuple[int, float]:
    return _filename_hits(row["path"], tokens), float(-row["rank"])

