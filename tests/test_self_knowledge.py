"""Kiki's description of herself must keep up with what the code accepts."""
import re

from kiki.self_knowledge import COMMAND_HELP, capabilities_text, self_knowledge_prompt
from kiki.terminal import INTERACTIVE_COMMANDS

PROMPT = self_knowledge_prompt(mode="chat", model_profile="auto")


def test_every_interactive_command_is_described() -> None:
    described = {word for command, _ in COMMAND_HELP for word in re.findall(r"/[a-z]+", command)}
    assert set(INTERACTIVE_COMMANDS) <= described


def test_every_subcommand_the_code_handles_is_in_her_self_knowledge() -> None:
    # Forms handled in terminal.py, folders_command.py, and personality handling.
    # Add a form here when a command gains one; this test then fails until
    # COMMAND_HELP (which feeds both /help and the model) mentions it.
    handled = [
        "/web URL", "/web alone", "/web clear", "/folders add PATH", "add browse", "/folders reindex",
        "/folders remove", "/find WORDS", "ext:", "in:", "name:", "after:", "before:", "larger:",
        "smaller:", "/find alone", "/sources all", "/personality preset", "/personality TRAIT",
        "/persona show, path, or reset", "/diagnostics copy", "/diagnostics save",
        "/database browse", "/workspace browse", "/model [auto|fast|smart|max]",
        "/forget NUMBER or TEXT", "/run [FILE.py]", "/apply FILE", "/new · /clear", "/quit · /exit",
    ]
    missing = [form for form in handled if form not in PROMPT]
    assert not missing


def test_key_facts_and_limits_are_stated() -> None:
    for fact in ["WEB", "KIKI_OFFLINE", "kiki-web-log.jsonl", ".docx", "no web search",
                 "not watched", "offline sandbox", "kiki index", "not used in WEB mode"]:
        assert fact in PROMPT, fact
    assert "/web clear" in capabilities_text()


def test_self_help_hints_match_questions_about_kiki() -> None:
    from kiki.self_knowledge import self_help_hints

    assert any("/web" in hint for hint in self_help_hints("Can you search the web for me?"))
    assert any("KIKI_OFFLINE" in hint for hint in self_help_hints("How do I turn off your internet access?"))
    assert any("/run" in hint for hint in self_help_hints("Can you run this Python code for me?"))
    assert any("/personality" in hint for hint in self_help_hints("How do I make you wittier?"))
    assert any("/folders remove" in hint for hint in self_help_hints("How do I stop indexing a folder?"))
    assert self_help_hints("Explain mercantilism in plain language.") == []
    assert len(self_help_hints("search the web, run code, be wittier, remember this folder")) == 3
