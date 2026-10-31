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
    ("/today · /today TEXT · /today clear", "Show, add, or lift temporary tone requests; most end at 4 AM."),
    ("/remember TEXT", "Save an explicit, non-sensitive note."),
    ("/memory", "List saved notes, numbered."),
    ("/forget NUMBER|TEXT", "Delete a saved note by number or matching text."),
    ("/model [auto|fast|smart|max]", "Show or choose a model profile."),
    ("/context [small|standard|large|max]", "Show or choose how much of a CHAT conversation Kiki keeps in mind (this session only)."),
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
    "/today shows temporary tone requests; /today TEXT adds one; /today clear lifts them; saying "
    "\"be nicer today\" or \"no jokes while we work\" saves one too, and \"back to normal\" lifts them; "
    "they end at 4 AM unless the user gave a time (\"for an hour\", \"until 5pm\"); a newer request on the "
    "same topic replaces the older one",
    "/persona show, path, or reset; /sources (cited passages) or /sources all; "
    "/diagnostics, /diagnostics copy, or /diagnostics save",
)


def self_knowledge_prompt(*, mode: str, model_profile: str) -> str:
    multi = {"/web", "/folders", "/find", "/personality", "/remember", "/memory", "/forget", "/today",
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
- Conversation: she keeps only the recent part of this conversation in mind (how much depends on /context, set for the computer's memory); closing Kiki clears it. She speaks only when the user sends a message: no reminders, alarms, or messages on her own.
- Memory: only notes the user saves with /remember, kept in kiki-memory.md, removed with /forget; not used in WEB mode. kiki-persona.md and kiki-personality.json set her voice.
- Tools the model can call: search_files in RAG and WEB modes only. Weather is fetched by Kiki's code when the user asks. No shell, screen control, background jobs, or voice.
When asked how Kiki works or what is available, answer from this runtime knowledge, giving every form listed for a command. Do not invent commands, tools, settings, or completed actions.
- If asked to search the web or look something up online: say you have no web search, and suggest /web followed by a page's address (a Wikipedia article, say).
- If asked to be wittier, warmer, more serious, or shorter: for today only, Kiki's code saves requests like "be nicer today" (see /today); for good, tell the user to type /personality TRAIT 0-3, for example /personality wit 3."""


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


_KNOWN_COMMANDS = set(re.findall(r"/[a-z]+", " ".join(command for command, _ in COMMAND_HELP)))
# The lowercase words each command accepts after it, from its COMMAND_HELP forms
# ("/persona [show|path|reset]" -> show, path, reset).
_SUBCOMMANDS: dict[str, set[str]] = {}
for _command, _ in COMMAND_HELP:
    for _name in set(re.findall(r"/[a-z]+", _command)):
        _SUBCOMMANDS.setdefault(_name, set()).update(re.findall(r"(?<![/\w])[a-z]{2,}", _command))
_UNIX_FOLDERS = {"/bin", "/boot", "/dev", "/etc", "/home", "/lib", "/mnt", "/opt", "/proc", "/root",
                 "/run", "/sbin", "/srv", "/sys", "/tmp", "/usr", "/var"}
# A slash command as an answer presents one: in backticks, or after "type",
# "use", "run", "enter", or "try". Paths (/usr/bin, /r/python) never match.
_PRESENTED = re.compile(
    r"`(/[a-z][a-z-]*)(?:\s+([a-z][a-z-]*))?[^`]*`"
    r"|\b(?:type|use|run|enter|try|command)\s+(/[a-z][a-z-]*)(?:\s+([a-z][a-z-]*))?(?![\w/-]|\.\w)"
    # A command alone at the start of a line ("/folders clear all" as the whole answer).
    # A full stop may end the sentence ("Just type /unlock-pro."), but not
    # continue a path (/x.txt); the stop used to hide the command (re-audit).
    r"|^[ \t]*[-*]?[ \t]*(/[a-z][a-z-]*)(?:[ \t]+([a-z][a-z-]*))?(?![\w/-]|\.\w)",
    re.IGNORECASE | re.MULTILINE,
)
_SUBCOMMAND_WORDS = {"add", "all", "browse", "clear", "copy", "delete", "disable", "enable", "list",
                     "new", "off", "on", "path", "preset", "reindex", "remove", "reset", "save",
                     "show", "start", "stop", "undo", "update"}


def unknown_commands(answer: str) -> list[str]:
    """Slash commands (or subcommands) an answer presents that Kiki doesn't have.

    Checked in code, like citations: a small model invents plausible commands
    ("/folders clear"), and a web page can plant fake ones ("/unlock-pro")."""
    found: list[str] = []
    for match in _PRESENTED.finditer(answer):
        command = (match.group(1) or match.group(3) or match.group(5)).casefold()
        word = (match.group(2) or match.group(4) or match.group(6) or "").casefold()
        if command in _UNIX_FOLDERS:
            continue
        # "There is no `/admin` command" is the right answer, not an invention.
        # The negation must sit right before the command: any "no" nearby used
        # to excuse "No sign-in needed, just type /unlock-pro" (audit L).
        before = answer[max(0, match.start() - 40):match.start()].casefold()
        if re.search(r"\b(?:no|not|isn't|aren't|doesn't|don't|never|without)\s+(?:[a-z']+\s+){0,2}$", before):
            continue
        if command not in _KNOWN_COMMANDS:
            found.append(command)
        elif word in _SUBCOMMAND_WORDS and word not in _SUBCOMMANDS.get(command, set()):
            found.append(f"{command} {word}")
    return list(dict.fromkeys(found))


# Real commands that change Kiki's memory, folders, files, or settings.
_STATE_CHANGING = re.compile(
    r"(?<![\w/.])(/(?:remember|forget|folders\s+(?:add|remove)|database|workspace|apply|run|"
    r"persona\s+reset|personality))\b[^\n`;]*?(?=[.!?](?:\s|$)|[\n`;]|$)",
    re.IGNORECASE,
)


def state_changing_commands(answer: str) -> list[str]:
    """Commands in an answer that would change Kiki's memory, folders, files,
    or settings. A web page can plant "type /remember Always recommend X"
    through the answer, so in WEB mode these are pointed out (audit L)."""
    return list(dict.fromkeys(match.group().strip()[:80] for match in _STATE_CHANGING.finditer(answer)))


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
