"""Parse untrusted files in a separate, limited process.

Documents in indexed folders and web pages are written by other people. A
crafted one can make a parser run for hours (quadratic HTML parsing in
Python 3.12.3, deeply nested Word XML) or inflate gigabytes (a PDF
decompression bomb). Parsing them in one long-lived child process, under a
Windows job object with a memory cap and a per-file time limit, means such a
file costs one failed file, never the session or the machine (audit A5-A8,
A11, A27).

The child is started on first use and reused; after a timeout or crash it is
killed and a fresh one starts for the next file.
"""
from __future__ import annotations

import base64
import json
import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from .extraction import ExtractedChunk, ExtractionError

FILE_TIMEOUT_S = 60.0
PAGE_TIMEOUT_S = 20.0
MEMORY_MIB = 1536


class IsolatedParser:
    """A reusable parsing child process with time and memory limits."""

    def __init__(self, timeout_s: float = FILE_TIMEOUT_S, memory_mib: int = MEMORY_MIB) -> None:
        self.timeout_s = timeout_s
        self.memory_mib = memory_mib
        self._process: subprocess.Popen[bytes] | None = None
        self._job: Any = None
        self._lines: queue.Queue[bytes | None] = queue.Queue()

    def __enter__(self) -> IsolatedParser:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def extract_file(self, path: Path) -> tuple[list[ExtractedChunk], str | None]:
        """Passages and title of one file, or ExtractionError (including time/memory limits)."""
        reply = self._request({"op": "file", "path": str(path)})
        chunks = [ExtractedChunk(**chunk) for chunk in reply["chunks"]]
        return chunks, reply.get("title")

    def html(self, data: bytes, encoding: str | None, *, main_only: bool,
             skip_hidden: bool) -> tuple[str | None, list[str], list[int]]:
        reply = self._request({"op": "html", "data": base64.b64encode(data).decode("ascii"),
                               "encoding": encoding, "main_only": main_only,
                               "skip_hidden": skip_hidden})
        return reply.get("title"), reply["paragraphs"], reply["sections"]

    def close(self) -> None:
        process, job = self._process, self._job
        self._process, self._job = None, None
        if process is not None:
            try:
                if process.stdin:
                    process.stdin.close()
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                process.kill()
        if job is not None:
            job.close()  # kills anything left in the job

    def _request(self, message: dict[str, Any]) -> dict[str, Any]:
        process = self._start()
        try:
            assert process.stdin is not None
            process.stdin.write(json.dumps(message).encode("utf-8") + b"\n")
            process.stdin.flush()
        except OSError as exc:
            self._kill()
            raise ExtractionError("the parser stopped unexpectedly") from exc
        try:
            line = self._lines.get(timeout=self.timeout_s)
        except queue.Empty:
            self._kill()
            raise ExtractionError(f"took longer than {self.timeout_s:.0f} s to read; skipped") from None
        if line is None:
            self._kill()
            raise ExtractionError("used too much memory or crashed while being read; skipped")
        reply = json.loads(line)
        if "error" in reply:
            raise ExtractionError(reply["error"])
        return reply

    def _start(self) -> subprocess.Popen[bytes]:
        if self._process is not None and self._process.poll() is None:
            return self._process
        self._kill()
        argv = [sys.executable, "-I", "-m", "kiki.parse_worker"]
        try:
            from .sandbox.jobs import Job

            self._job = Job(self.memory_mib * 2**20)
            process = self._job.start(argv, stdin=True)
        except (ImportError, OSError, AttributeError):
            # No job objects here: still a separate process with a time limit.
            self._job = None
            process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.DEVNULL)
        self._process = process
        self._lines = queue.Queue()
        threading.Thread(target=self._read, args=(process, self._lines), daemon=True).start()
        return process

    @staticmethod
    def _read(process: subprocess.Popen[bytes], lines: queue.Queue[bytes | None]) -> None:
        assert process.stdout is not None
        for line in process.stdout:
            lines.put(line)
        lines.put(None)  # the child exited

    def _kill(self) -> None:
        process, job = self._process, self._job
        self._process, self._job = None, None
        if process is not None and process.poll() is None:
            process.kill()
        if job is not None:
            job.close()


def parse_html_isolated(data: bytes, encoding: str | None, *, main_only: bool,
                        skip_hidden: bool) -> tuple[str | None, list[str], list[int]]:
    """One web page parsed in a short-lived limited child; ExtractionError on limits."""
    with IsolatedParser(timeout_s=PAGE_TIMEOUT_S) as parser:
        return parser.html(data, encoding, main_only=main_only, skip_hidden=skip_hidden)
