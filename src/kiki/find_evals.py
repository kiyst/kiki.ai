"""Randomized-folder evaluation for /find.

Each seed builds a fresh personal-looking folder (documents, opaque files such
as spreadsheets and scans, decoys that share words with the targets, a
dependency folder that must be skipped), indexes it, deletes some targets to
test freshness, and asks file-finding questions with known answers.

Development seeds were used while tuning; holdout seeds were not. The
generator itself was written alongside the ranker, so holdout seeds test
randomness, not unseen phrasing: real-folder checks are still needed.
"""
from __future__ import annotations

import logging
import os
import random
import tempfile
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .finding import FileFinder
from .retrieval import TextIndex

DEVELOPMENT_SEEDS = (1, 2, 3)
HOLDOUT_SEEDS = (101, 102, 103, 104, 105)

CODENAMES = [
    "kestrel", "marigold", "basalt", "orchid", "tundra", "falcon", "juniper", "cobalt",
    "saffron", "quartz", "harbor", "willow", "ember", "glacier", "lantern", "meridian",
]
DOC_KINDS = ["budget", "invoice", "roadmap", "timeline", "contract", "estimate", "schedule", "inventory"]
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december"]
TOPICS = [
    ("sourdough", "starter"), ("mortgage", "refinance"), ("passport", "renewal"),
    ("vaccination", "record"), ("thermostat", "wiring"), ("kayak", "rental"),
    ("orthodontist", "braces"), ("scholarship", "essay"), ("warranty", "claim"),
    ("aquarium", "filter"), ("bicycle", "derailleur"), ("pottery", "glaze"),
    ("telescope", "eyepiece"), ("beekeeping", "hive"), ("chess", "opening"),
    ("piano", "recital"), ("greenhouse", "irrigation"), ("wedding", "seating"),
    ("lease", "deposit"), ("carpool", "rota"), ("allergy", "dosage"), ("roof", "gutter"),
]
COMMON = ("the we a plan meeting notes update draft review team week call follow list "
          "ideas project time next today items progress summary report data share "
          "check status budget final version copy new old misc").split()
OPAQUE = [".xlsx", ".docx", ".jpg", ".png", ".zip", ".pptx", ".mp4"]


@dataclass
class Case:
    kind: str
    query: str
    target: str | None  # path relative to the fixture root; None = nothing fits
    stale: bool = False


def _sentence(rng: random.Random, extra: list[str] = ()) -> str:
    words = rng.choices(COMMON, k=rng.randint(6, 12)) + list(extra)
    rng.shuffle(words)
    return " ".join(words).capitalize() + "."


def _write(root: Path, relative: str, content: str | bytes, when: datetime | None = None) -> str:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    if when is not None:
        stamp = when.timestamp()
        os.utime(path, (stamp, stamp))
    return relative


def build_fixture(root: Path, seed: int) -> list[Case]:
    rng = random.Random(seed)
    cases: list[Case] = []
    codenames = rng.sample(CODENAMES, 8)
    topics = rng.sample(TOPICS, 10)
    opaque = lambda: rng.randbytes(rng.randint(200, 3000))

    # Decoys: everyday clutter, some sharing words with targets.
    for number in range(160):
        style = rng.random()
        if style < 0.3:
            name = f"Pictures/{rng.choice(['2023', '2024', '2025'])}/IMG_{rng.randint(1000, 9999)}.jpg"
            _write(root, name, opaque())
        elif style < 0.6:
            folder = rng.choice(["Documents/Work/Meetings", "Documents/Personal", "Desktop", "Downloads"])
            body = "\n\n".join(
                _sentence(rng, [rng.choice(topics)[0]] if rng.random() < 0.3 else [])
                for _ in range(rng.randint(2, 6))
            )
            _write(root, f"{folder}/{rng.choice(['notes', 'draft', 'meeting-notes', 'todo'])}-{number}.md", body)
        else:
            stem = f"{rng.choice(codenames)}-{rng.choice(DOC_KINDS)}-{rng.choice(MONTHS)}"
            folder = rng.choice(["Documents/Work/Projects", "Downloads", "Desktop"])
            _write(root, f"{folder}/{stem}-v{number}{rng.choice(OPAQUE)}", opaque())

    # Must never be found: dependency folders are skipped by the catalog.
    for codename in codenames:
        _write(root, f"Documents/Work/app/node_modules/{codename}/{codename}-budget.js", "x")

    # Name targets: opaque files found only by name.
    used: set[tuple[str, str, str]] = set()
    for _ in range(6):
        codename, kind, month = rng.choice(codenames), rng.choice(DOC_KINDS), rng.choice(MONTHS)
        if (codename, kind, month) in used:
            continue
        used.add((codename, kind, month))
        folder = f"Documents/Work/Projects/{codename.capitalize()}"
        target = _write(root, f"{folder}/{codename.capitalize()}_{kind.capitalize()}_{month.capitalize()}.xlsx", opaque())
        # Same project and kind, another month: the month must decide.
        other = rng.choice([m for m in MONTHS if m != month])
        _write(root, f"{folder}/{codename.capitalize()}_{kind.capitalize()}_{other.capitalize()}.xlsx", opaque())
        cases.append(Case("name", f"the {codename} {kind} spreadsheet from {month}", target))

    # Content targets: generic names, found only by what they say.
    for number, (first, second) in enumerate(topics[:5]):
        body = "\n\n".join(_sentence(rng, [first, second] if index == 1 else []) for index in range(4))
        target = _write(root, f"Documents/Personal/notes-{1000 + number}.txt", body)
        # Half the questions use another form of a word than the file does.
        plural = second[:-1] if second.endswith("s") else second + "s"
        asked = plural if number % 2 else second
        cases.append(Case("contents", f"my notes about {first} {asked}", target))

    # Title targets: a Markdown heading names the document.
    for number, (first, second) in enumerate(topics[5:8]):
        body = f"# {first.capitalize()} {second.capitalize()} Checklist\n\n" + _sentence(rng)
        target = _write(root, f"Desktop/untitled-{number}.md", body)
        cases.append(Case("title", f"{first} {second} checklist", target))

    # Folder targets: a scan known only by where it lives.
    for year in rng.sample(["2021", "2022", "2023", "2024"], 3):
        target = _write(root, f"Documents/Taxes/{year}/scan_{rng.randint(100, 999)}.pdf", opaque())
        _write(root, f"Documents/Taxes/{year}/receipts-{year}.zip", opaque())
        cases.append(Case("folder", f"{year} taxes scan", target))

    # Noise: the question includes a word that appears nowhere.
    first, second = topics[8]
    target = _write(root, f"Documents/Personal/{first}-{second}.docx", opaque())
    cases.append(Case("noisy", f"that old {first} {second} thing from grandma", target))

    # Dates: two same-named reports; the filter decides.
    codename = codenames[0]
    _write(root, f"Documents/Archive/{codename}-report.docx", opaque(), datetime(2023, 5, 1, tzinfo=UTC))
    target = _write(root, f"Documents/Work/{codename}-report.docx", opaque(), datetime(2025, 9, 1, tzinfo=UTC))
    cases.append(Case("dated", f"{codename} report after:2025", target))

    # Freshness: indexed, then deleted; it must never come back.
    first, second = topics[9]
    stale = _write(root, f"Downloads/{first}-{second}-final.pdf", opaque())
    cases.append(Case("stale", f"{first} {second} final", stale, stale=True))

    # Ambiguous: two files fit the question equally; "Likely" would overclaim.
    codename, kind = codenames[1], rng.choice(DOC_KINDS)
    for quarter in ("q1", "q2"):
        _write(root, f"Documents/Work/{codename}_{kind}_{quarter}.xlsx", opaque())
    cases.append(Case("ambiguous", f"{codename} {kind}", None))

    # Nothing fits: Kiki must not sound sure.
    cases.append(Case("absent", "zeppelin harpsichord manual", None))
    cases.append(Case("absent", "quokka vineyard brochure", None))
    return cases


def run_find_eval(seeds: tuple[int, ...] = DEVELOPMENT_SEEDS, limit: int = 3) -> dict[str, Any]:
    # The fake scans are unreadable on purpose; pypdf's warnings are noise here.
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    rows: list[dict[str, Any]] = []
    for seed in seeds:
        with tempfile.TemporaryDirectory(prefix=f"kiki-find-{seed}-") as temporary:
            base = Path(temporary)
            root = base / "home"
            cases = build_fixture(root, seed)
            index = TextIndex(base / "index.sqlite3")
            index.index_root(root)
            for case in cases:
                if case.stale:
                    (root / case.target).unlink()
            finder = FileFinder(index)
            for case in cases:
                started = time.perf_counter()
                result = finder.find(case.query, limit)
                elapsed = time.perf_counter() - started
                paths = [Path(c.path).relative_to(root.resolve()).as_posix() for c in result.candidates]
                labels = [c.confidence for c in result.candidates]
                rows.append({
                    "seed": seed, "kind": case.kind, "query": case.query, "target": case.target,
                    "returned": paths, "labels": labels,
                    "rank": paths.index(case.target) + 1 if case.target in paths and not case.stale else None,
                    "stale_returned": case.stale and case.target in paths,
                    "dependency_returned": any("node_modules" in path for path in paths),
                    "invalid_paths": sum(not Path(c.path).is_file() for c in result.candidates),
                    "seconds": round(elapsed, 4),
                })
            del index, finder
    return summarize(rows, seeds, limit)


def summarize(rows: list[dict[str, Any]], seeds: tuple[int, ...], limit: int) -> dict[str, Any]:
    findable = [row for row in rows if row["kind"] not in {"stale", "absent", "ambiguous"}]
    by_kind: dict[str, dict[str, Any]] = {}
    for kind in sorted({row["kind"] for row in findable}):
        group = [row for row in findable if row["kind"] == kind]
        by_kind[kind] = {
            "cases": len(group),
            "recall@1": _share(row["rank"] == 1 for row in group),
            f"recall@{limit}": _share(row["rank"] is not None for row in group),
        }
    # Calibration: when the top answer carries a label, how often is it right?
    calibration: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not row["labels"]:
            continue
        label = row["labels"][0]
        entry = calibration.setdefault(label, {"shown": 0, "correct": 0})
        entry["shown"] += 1
        entry["correct"] += int(row["rank"] == 1)
    for entry in calibration.values():
        entry["precision"] = round(entry["correct"] / entry["shown"], 3)
    absent = [row for row in rows if row["kind"] == "absent"]
    ambiguous = [row for row in rows if row["kind"] == "ambiguous"]
    return {
        "seeds": list(seeds),
        "cases": len(rows),
        "recall@1": _share(row["rank"] == 1 for row in findable),
        f"recall@{limit}": _share(row["rank"] is not None for row in findable),
        "by_kind": by_kind,
        "top_label_precision": dict(sorted(calibration.items())),
        "absent_with_likely": sum(bool(row["labels"]) and row["labels"][0] == "Likely" for row in absent),
        "ambiguous_with_likely": sum(
            bool(row["labels"]) and row["labels"][0] == "Likely" for row in ambiguous
        ),
        "stale_returned": sum(row["stale_returned"] for row in rows),
        "dependency_returned": sum(row["dependency_returned"] for row in rows),
        "invalid_paths": sum(row["invalid_paths"] for row in rows),
        "slowest_seconds": max(row["seconds"] for row in rows),
        "failures": [row for row in findable if row["rank"] != 1],
        "label_counts": dict(Counter(row["labels"][0] for row in rows if row["labels"])),
    }


def _share(values: Any) -> float:
    values = list(values)
    return round(sum(values) / len(values), 3) if values else 0.0
