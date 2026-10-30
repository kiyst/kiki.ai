"""Code blocks exactly as the answer displays them, for /run and /apply.

Blocks are found with the same Markdown parser Rich uses to draw the answer,
so a block the user can't see (inside an HTML comment, say) is never picked,
and a ~~~ fence counts like a ``` one. Picking with a regex let /run and
/apply choose code that was hidden from the rendered answer (audit A4).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from markdown_it import MarkdownIt

# The configuration rich.markdown.Markdown uses; keep the two identical.
_PARSER = MarkdownIt().enable("strikethrough").enable("table")
_ANY_FENCE = re.compile(r"^[ \t]*(```|~~~)", re.MULTILINE)


@dataclass(frozen=True)
class CodeBlock:
    language: str
    code: str
    number: int  # 1-based position among displayed blocks
    total: int


def displayed_blocks(answer: str) -> list[CodeBlock]:
    """Fenced and indented code blocks the rendered answer shows, in order."""
    found = [(token.info.strip().split()[0].casefold() if token.info.strip() else "", token.content)
             for token in _PARSER.parse(answer)
             if token.type in {"fence", "code_block"} and token.content.strip()]
    return [CodeBlock(language, code.rstrip() + "\n", number, len(found))
            for number, (language, code) in enumerate(found, start=1)]


def hidden_code(answer: str) -> bool:
    """True when the answer holds code fences the rendered answer doesn't show."""
    fences = len(_ANY_FENCE.findall(answer)) // 2
    return fences > len([block for block in displayed_blocks(answer) if block.code])
