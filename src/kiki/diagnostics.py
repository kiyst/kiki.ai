from __future__ import annotations

import platform
import sys
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any


def build_diagnostics(
    *,
    database: Path,
    mode: str,
    model_profile: str,
    selected_model: str,
    embedding_model: str,
    index_health: dict[str, Any],
    tool_catalog: dict[str, dict[str, Any]],
    retrieval: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        package_version = version("kiki-local")
    except PackageNotFoundError:
        package_version = "development"
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "kiki_version": package_version,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "mode": mode,
        "model_profile": model_profile,
        "selected_model": selected_model,
        "embedding_model": embedding_model,
        "database": str(database.resolve()),
        "index": index_health,
        "retrieval": retrieval or {},
        "tools": tool_catalog,
        "note": "Environment variable values and conversation content are intentionally omitted.",
    }


def diagnostics_markdown(report: dict[str, Any]) -> str:
    lines = ["# Kiki diagnostics", ""]
    for key in (
        "generated_at",
        "kiki_version",
        "python",
        "platform",
        "mode",
        "model_profile",
        "selected_model",
        "embedding_model",
        "database",
    ):
        lines.append(f"- **{key.replace('_', ' ').title()}:** {report[key]}")
    lines.extend(["", "## Index", "", "```text", str(report["index"]), "```"])
    if report.get("retrieval"):
        lines.extend(["", "## Retrieval settings", ""])
        lines.extend(f"- `{key}`: {value}" for key, value in report["retrieval"].items())
    lines.extend(["", "## Tool policies", ""])
    for name, details in report["tools"].items():
        lines.append(
            f"- `{name}`: {details['risk']}; confirmation="
            f"{details['confirmation_required']}"
        )
    lines.extend(["", str(report["note"]), ""])
    return "\n".join(lines)
