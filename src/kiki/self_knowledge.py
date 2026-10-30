from __future__ import annotations


COMMAND_HELP = (
    ("/chat [message]", "Switch to ordinary local conversation."),
    ("/rag [question]", "Switch to evidence-grounded document Q&A."),
    ("/retry", "Regenerate the last response."),
    ("/copy", "Copy the last response to the clipboard."),
    ("/sources [all]", "Show the passages the last answer cited (all: every retrieved passage)."),
    ("/find WORDS", "Find whole files in indexed folders; filters: ext:pdf in:FOLDER after:2025 before:2026-03 larger:10MB."),
    ("/folders [add|reindex|remove]", "List, add, reindex, or forget the folders Kiki indexes; files on disk are never changed."),
    ("/web URL [QUESTION]", "Read one public web page and switch to WEB mode, where messages ask about it with citations; /web returns to it, /web clear forgets it."),
    ("/run [FILE.py]", "Run the last answer's Python (or a copy of a .py file) in the sandbox after you confirm."),
    ("/workspace [PATH|browse]", "Choose the folder /apply may write into (this session only)."),
    ("/apply FILE", "Save the last answer's code to a file in the workspace after you approve the diff."),
    ("/history", "Show the last ten prompts in this conversation."),
    ("/save [PATH]", "Browse for a folder or export directly to a Markdown path."),
    ("/new", "Start a fresh conversation in the active mode."),
    ("/weather City, State", "Fetch current Open-Meteo weather."),
    ("/database [PATH|browse]", "Show, directly set, or browse for a RAG database."),
    ("/status", "Show the active configuration."),
    ("/doctor", "Check Ollama, index integrity, and provider health."),
    ("/debug", "Toggle validated tool traces."),
    ("/personality", "Adjust warmth, wit, opinions, and verbosity."),
    ("/persona [show|reset]", "Inspect or reset the editable persona file."),
    ("/remember TEXT", "Save an explicit non-sensitive memory."),
    ("/forget NUMBER", "Delete the numbered memory shown by /memory."),
    ("/memory", "Show numbered durable memories."),
    ("/model [auto|fast|smart|max]", "Inspect or select a model profile."),
    ("/diagnostics [copy|save]", "Create a privacy-filtered support report."),
    ("/capabilities", "Show Kiki's commands, tools, and current limitations."),
    ("/clear", "Alias for /new."),
    ("/quit", "Close the terminal session."),
)


def self_knowledge_prompt(*, mode: str, model_profile: str) -> str:
    commands = "; ".join(command for command, _ in COMMAND_HELP)
    return f"""Kiki runtime knowledge:
- Current mode: {mode.upper()}. Current model profile: {model_profile.upper()}.
- CHAT is ordinary local conversation. RAG searches the selected indexed SQLite corpus and requires verifiable source citations.
- Available model tools: get_weather; search_files in RAG mode only. Tool arguments are schema-validated before execution.
- Available terminal commands: {commands}
- Durable user memories are explicit, numbered, stored in kiki-memory.md, and removed with /forget NUMBER.
- kiki-persona.md controls conversational identity; kiki-personality.json stores tone sliders.
- To find a whole file ("I can't find the file about X"), the user types /find with a description; it searches every file in the indexed folders, including ones whose contents Kiki cannot read, and shows ranked candidates with confidence and paths. Kiki cannot run /find herself yet; suggest it. Kiki only knows folders the user added with /folders add (or kiki index); she never browses the disk on her own, and folders are not watched, so /folders reindex picks up new files.
- Kiki goes online only when the user types /web URL (one page, read and cited like a document) or asks about weather (Open-Meteo); setting KIKI_OFFLINE turns both off. She cannot browse, follow links, or search the web herself, and cannot read pages behind logins or pages built with JavaScript. If a question needs current information, suggest /web with a relevant page, such as a Wikipedia article. /web switches to WEB mode, where each message searches that page. In CHAT and RAG modes no web page is visible to you, even one discussed earlier: never say what a page does or does not contain there; tell the user to type /web to return to the page and ask again.
- Kiki can explain, draft, reason about, and generate code. She cannot run code herself: the user can run the Python in her last answer with /run, which shows the code, asks for confirmation, and runs it in an offline sandbox with no file access. Never claim code was run unless the user ran it. She cannot edit files herself: with /apply FILE the user saves her last code block into a workspace folder they chose, after reviewing a diff; never claim a file was changed unless the user applied it. She has no shell, screen-control, job-engine, or voice tool.
When asked how Kiki works or what is available, answer from this runtime knowledge. Do not invent commands, tools, settings, or completed actions."""


def capabilities_text() -> str:
    lines = ["Modes and tools:", "• CHAT · conversation, reasoning, drafting, and code generation", "• RAG · indexed document search with verified citations", "• Find · whole-file search in indexed folders with /find", "• Web · read one public page you link with /web, only when you ask", "• Weather · current Open-Meteo conditions and forecast", "", "Commands:"]
    lines.extend(f"• {command} · {description}" for command, description in COMMAND_HELP)
    lines.extend(
        [
            "",
            "Current limits:",
            "• Python runs only through /run, in an offline sandbox, after you confirm",
            "• Files change only through /apply, inside your chosen workspace, after you approve a diff",
            "• No web search; Kiki reads only pages you link with /web",
            "• No shell commands",
            "• No screen control",
            "• No job engine",
            "• No voice",
        ]
    )
    return "\n".join(lines)
