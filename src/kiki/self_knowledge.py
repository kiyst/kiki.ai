from __future__ import annotations

import re

# Every form each command accepts, in the command column, because the model
# sees only that column (the descriptions would cost too much of its 4K-token
# reading space). /help and /capabilities show both columns.
COMMAND_HELP = (
    ("/chat [message]", "Switch to ordinary local conversation."),
    ("/rag [question]", "Switch to answers from your indexed documents, with citations."),
    ("/web URL [QUESTION] · /web · /web clear", "Read one public web page and switch to WEB mode, where messages ask about it; /web returns to it, /web clear forgets it."),
    ("/find WORDS [ext: in: name: after: before: larger: smaller:] · /find", "Find whole files in indexed folders; /find alone shows the last results again."),
    ("/folders · /folders add PATH|browse · /folders reindex [NUMBER|all] · /folders remove NUMBER", "List, add, re-read, or forget indexed folders; files on disk are never changed."),
    ("/sources [all]", "Show the passages the last answer cited (all: every passage read)."),
    ("/run [FILE.py]", "Run the last answer's Python (or a copy of a .py file) in the offline sandbox, after you confirm."),
    ("/workspace · /workspace PATH · /workspace browse", "Show or choose the folder /apply may write into (this session only)."),
    ("/apply FILE", "Save the last answer's code to a file in the workspace, after you approve the diff."),
    ("/retry", "Regenerate the last response."),
    ("/copy", "Copy the last response to the clipboard."),
    ("/history", "Show the last ten prompts in this conversation."),
    ("/save [PATH]", "Save the conversation as Markdown (no path opens a folder browser)."),
    ("/new · /clear", "Start a fresh conversation in the active mode."),
    ("/weather City, State", "Current Open-Meteo weather and a short forecast."),
    ("/database · /database PATH · /database browse", "Show or switch the document library."),
    ("/status", "Show the active configuration."),
    ("/doctor", "Check Ollama, models, the index, and weather."),
    ("/debug", "Toggle search steps and tool calls under each answer."),
    ("/personality · /personality preset NAME · /personality TRAIT 0-3", "Show or set warmth, wit, opinions, and verbosity."),
    ("/persona [show|path|reset]", "Show, locate, or reset the editable persona file."),
    ("/remember TEXT", "Save an explicit, non-sensitive note."),
    ("/memory", "List saved notes, numbered."),
    ("/forget NUMBER|TEXT", "Delete a saved note by number or matching text."),
    ("/model [auto|fast|smart|max]", "Show or choose a model profile."),
    ("/diagnostics [copy|save]", "A privacy-filtered support report."),
    ("/capabilities", "What Kiki can and cannot do."),
    ("/help", "All commands."),
    ("/quit · /exit", "Close the session."),
)


# Commands with several forms, one line each with every form spelled out: in a
# single long list the model missed "/web clear" and invented "/folders clear".
COMMAND_FORMS = (
    "/web URL [QUESTION] opens a page in WEB mode; /web alone returns to it; /web clear forgets it",
    "/folders lists indexed folders; /folders add PATH (or add browse); /folders reindex [NUMBER|all]; "
    "/folders remove NUMBER forgets one (files stay on disk)",
    "/find WORDS finds files, with filters ext:pdf in:FOLDER name:WORD after:2025 before:2026-03 "
    "larger:10MB smaller:1MB; /find alone shows the last results again",
    "/personality shows tone settings; /personality TRAIT 0-3 sets warmth, wit, opinions, or "
    "verbosity (e.g. /personality wit 3); /personality preset NAME",
    "/remember TEXT saves a note; /memory lists notes; /forget NUMBER or TEXT deletes one",
    "/persona show, path, or reset; /sources (cited passages) or /sources all; "
    "/diagnostics, /diagnostics copy, or /diagnostics save",
)


def self_knowledge_prompt(*, mode: str, model_profile: str) -> str:
    multi = {"/web", "/folders", "/find", "/personality", "/remember", "/memory", "/forget",
             "/persona", "/sources", "/diagnostics"}
    others = "; ".join(command for command, _ in COMMAND_HELP if command.split()[0] not in multi)
    forms = "\n".join(f"  - {line}" for line in COMMAND_FORMS)
    return f"""Kiki runtime knowledge:
- Mode: {mode.upper()}; model profile: {model_profile.upper()}. Modes: CHAT (conversation, writing, code), RAG (answers only from indexed documents, cited), WEB (answers only from the page opened with /web, cited). Each mode has its own history.
- Commands with several forms (these are all the forms; there are no others):
{forms}
- Other commands: {others}
- Also from a terminal: kiki run (this chat), and one-off kiki chat, rag, find, index FOLDER, embed, weather, doctor, sandbox setup.
- Documents: reads .txt, .md, .pdf with text (not scans), .docx, .html; cites lines, pages, or paragraphs. Only folders the user added with /folders add or kiki index; never browses the disk; folders are not watched (/folders reindex picks up changes). /find also lists files she cannot read, by name, folder, and type. She cannot run /find herself; suggest it.
- Web: online only when the user types /web or asks about weather (Open-Meteo); KIKI_OFFLINE=1 blocks both. One public page at a time, read by meaning and words; no web search, no following links, no logins, no JavaScript-built pages, no PDFs from the web. Requests are announced and logged in kiki-web-log.jsonl. Local addresses are refused, hidden text and text aimed at AI assistants are left out, and unsupported details are flagged. In CHAT and RAG no page is visible to you: never say what a page contains there; tell the user to type /web to return to it.
- Code: she writes and explains code but cannot run it; the user runs it with /run in an offline sandbox with no file access, and saves it with /apply after reviewing a diff. Never claim code ran or a file changed unless the user did it.
- Memory: only notes the user saves with /remember, kept in kiki-memory.md, removed with /forget; not used in WEB mode. kiki-persona.md and kiki-personality.json set her voice.
- Tools the model can call: get_weather; search_files in RAG and WEB modes. No shell, screen control, background jobs, or voice.
When asked how Kiki works or what is available, answer from this runtime knowledge, giving every form listed for a command. Do not invent commands, tools, settings, or completed actions.
- If asked to search the web or look something up online: say you have no web search, and suggest /web followed by a page's address (a Wikipedia article, say).
- If asked to be wittier, warmer, more serious, or shorter: you can't change your own settings; tell the user to type /personality TRAIT 0-3, for example /personality wit 3."""


# Topic -> the facts to put in front of the model when a message is about that
# ability. In one long block of instructions, a 4B model's generic replies
# ("I can't run code", "I don't have internet access") won over the facts;
# the same facts placed beside the question are used.
_SELF_TOPICS = (
    (r"\b(search|look (it |this |that )?up|google|browse|internet|online|web\s?site|web\s?page|url|link)\b",
     "No web search. /web followed by a page's address reads that one page (WEB mode); /web returns "
     "to it; /web clear forgets it. KIKI_OFFLINE=1 blocks all internet use (web pages and weather)."),
    (r"\b(offline|internet access|go online|connect(ion)?|network)\b",
     "Kiki goes online only for /web and weather. Setting the environment variable KIKI_OFFLINE=1 "
     "blocks both."),
    (r"\b(run|execute|test)\b.{0,30}\b(code|python|script|program|this|it)\b",
     "Kiki can't run code herself. The user types /run to run the Python in her last answer (or "
     "/run FILE.py) in an offline sandbox with no file access, after confirming."),
    (r"\b(save|write|edit|apply|change|modify)\b.{0,30}\b(file|code|my project)\b",
     "Kiki can't edit files herself. /workspace PATH chooses a folder; /apply FILE saves her last "
     "code block there after the user approves a diff."),
    (r"\b(personality|tone|witty|wittier|funn(y|ier)|warm(er)?|serious|shorter|verbose|"
     r"concise|opinionated|sarcastic|nicer)\b",
     "Kiki can't change her own settings. /personality TRAIT 0-3 sets warmth, wit, opinions, or "
     "verbosity (e.g. /personality wit 3); /personality preset NAME; /personality shows them."),
    (r"\b(remember|memory|memories|forget|know about me)\b",
     "Kiki remembers only notes saved with /remember TEXT; /memory lists them; /forget NUMBER or "
     "TEXT deletes one. They are kept in kiki-memory.md."),
    (r"\b(folder|folders|index(ed|ing)?|reindex)\b",
     "/folders lists indexed folders; /folders add PATH (or add browse); /folders reindex "
     "[NUMBER|all] picks up changes; /folders remove NUMBER forgets one (files stay on disk)."),
    (r"\b(find|lost|where is|locate)\b.{0,30}\b(file|document|pdf|spreadsheet|photo)s?\b|\bfound\b",
     "/find WORDS searches every file in indexed folders (filters ext: in: name: after: before: "
     "larger: smaller:); /find alone shows the last results again."),
    (r"\b(commands?|what can you do|capabilit(y|ies)|features?|help)\b",
     "/help lists every command and /capabilities shows what Kiki can and cannot do."),
)


def self_help_hints(message: str, limit: int = 3) -> list[str]:
    """The self-documentation lines relevant to a message about Kiki's abilities."""
    lowered = message.casefold()
    hints = [fact for pattern, fact in _SELF_TOPICS if re.search(pattern, lowered)]
    return list(dict.fromkeys(hints))[:limit]


def capabilities_text() -> str:
    lines = [
        "Modes and tools:",
        "• CHAT · conversation, reasoning, drafting, and code generation",
        "• RAG · answers from your indexed documents (.txt .md .pdf .docx .html), with citations",
        "• WEB · answers from one public page you open with /web, with citations",
        "• Find · whole-file search in indexed folders with /find",
        "• Weather · current Open-Meteo conditions and forecast",
        "",
        "Commands:",
    ]
    lines.extend(f"• {command} · {description}" for command, description in COMMAND_HELP)
    lines.extend(
        [
            "",
            "Current limits:",
            "• Python runs only through /run, in an offline sandbox, after you confirm",
            "• Files change only through /apply, inside your chosen workspace, after you approve a diff",
            "• No web search; Kiki reads only pages you link with /web (KIKI_OFFLINE=1 turns the web off)",
            "• Folders are not watched; /folders reindex picks up changes",
            "• No shell commands, screen control, background jobs, or voice",
        ]
    )
    return "\n".join(lines)
