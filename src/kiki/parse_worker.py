"""Child process for isolation.py: parses one request per stdin line.

Started as `python -I -m kiki.parse_worker`. Each request is a JSON line;
each reply is one JSON line with the result or an "error" message. Nothing
here touches the index; it only reads the named file or the given bytes.
"""
from __future__ import annotations

import base64
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .documents import html_document
from .extraction import ExtractionError, document_title, extract_chunks


def handle(request: dict[str, Any]) -> dict[str, Any]:
    if request.get("op") == "file":
        path = Path(request["path"])
        chunks = extract_chunks(path)
        return {"chunks": [asdict(chunk) for chunk in chunks], "title": document_title(path)}
    if request.get("op") == "html":
        title, paragraphs, sections = html_document(
            base64.b64decode(request["data"]), request.get("encoding"),
            main_only=bool(request.get("main_only")), skip_hidden=bool(request.get("skip_hidden")))
        return {"title": title, "paragraphs": paragraphs, "sections": sections}
    return {"error": "unknown request"}


def main() -> None:
    for line in sys.stdin.buffer:
        try:
            reply = handle(json.loads(line))
        except ExtractionError as exc:
            reply = {"error": str(exc)}
        except MemoryError:
            reply = {"error": "used too much memory while being read; skipped"}
        except Exception as exc:  # a malformed file is that file's failure only
            reply = {"error": f"could not be read ({type(exc).__name__})"}
        sys.stdout.buffer.write(json.dumps(reply, ensure_ascii=False).encode("utf-8") + b"\n")
        sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
