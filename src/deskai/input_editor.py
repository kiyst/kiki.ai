from __future__ import annotations

import sys
from typing import Any, Protocol
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.clipboard.pyperclip import PyperclipClipboard
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.filters import has_selection
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory, InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.selection import SelectionType


class PromptReader(Protocol):
    def prompt(self, mode: str, debug: bool = False) -> str: ...


class PlainInput:
    """Line-at-a-time fallback for pipes, scripts, and non-console terminals."""

    def __init__(self, stream: Any = None, echo: Any = None) -> None:
        self._stream = stream or sys.stdin
        self._echo = echo or sys.stdout

    def prompt(self, mode: str, debug: bool = False) -> str:
        suffix = " · debug" if debug else ""
        self._echo.write(f"{mode.upper()}{suffix} you > ")
        self._echo.flush()
        line = self._stream.readline()
        if not line:
            raise EOFError
        line = line.rstrip("\r\n")
        if not self._stream.isatty():
            # Piped input is not echoed by a terminal; show it in the transcript.
            self._echo.write(line + "\n")
        return line


def create_chat_input(
    *, history_path: Path | None = None, commands: tuple[str, ...] = ()
) -> PromptReader:
    """Use the rich editor on an interactive console, otherwise plain lines."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return PlainInput()
    try:
        return ChatInput(history_path=history_path, commands=commands)
    except Exception:
        # prompt_toolkit refuses some terminals (for example mintty without
        # winpty); a working plain prompt is better than a traceback.
        return PlainInput()


class ChatInput:
    """Terminal-native multiline editor with familiar clipboard behavior."""

    def __init__(
        self,
        *,
        history_path: Path | None = None,
        commands: tuple[str, ...] = (),
        input: Any = None,
        output: Any = None,
    ) -> None:
        bindings = KeyBindings()

        @bindings.add("enter")
        def submit(event: Any) -> None:
            event.current_buffer.validate_and_handle()

        @bindings.add("escape", "enter")
        @bindings.add("f2")
        def newline(event: Any) -> None:
            event.current_buffer.insert_text("\n")

        @bindings.add("c-a")
        def select_all(event: Any) -> None:
            buffer = event.current_buffer
            buffer.cursor_position = 0
            buffer.start_selection(selection_type=SelectionType.CHARACTERS)
            buffer.cursor_position = len(buffer.text)

        @bindings.add("c-c", filter=has_selection)
        def copy(event: Any) -> None:
            event.app.clipboard.set_data(
                event.current_buffer.copy_selection(_cut=False)
            )

        @bindings.add("c-v")
        def paste(event: Any) -> None:
            event.current_buffer.paste_clipboard_data(event.app.clipboard.get_data())

        history = FileHistory(str(history_path)) if history_path else InMemoryHistory()
        command_completer = WordCompleter(commands, ignore_case=True, sentence=True)
        self._session: PromptSession[str] = PromptSession(
            history=history,
            auto_suggest=AutoSuggestFromHistory(),
            completer=command_completer,
            complete_while_typing=False,
            complete_in_thread=False,
            clipboard=PyperclipClipboard(),
            key_bindings=bindings,
            multiline=True,
            # Let the terminal own mouse drag events so users can highlight and
            # copy both conversation output and the current input normally.
            mouse_support=False,
            enable_open_in_editor=False,
            input=input,
            output=output,
            prompt_continuation=lambda width, line_number, is_soft_wrap: (
                " " * max(0, width - 3) + "│ "
            ),
        )

    def prompt(self, mode: str, debug: bool = False) -> str:
        color = "ansimagenta" if mode == "rag" else "ansicyan"
        suffix = " · debug" if debug else ""
        message = HTML(
            f"<b><{color}>{mode.upper()}{suffix}</{color}></b> <b>you &gt;</b> "
        )
        return self._session.prompt(
            message,
            bottom_toolbar=HTML(
                " <b>Enter</b> send  ·  <b>Alt+Enter/F2</b> newline  ·  "
                "<b>Tab</b> commands  ·  <b>↑</b> history  ·  "
                "<b>Ctrl+A/C/V/Z</b> select/copy/paste/undo  ·  <b>Ctrl+D</b> exit "
            ),
        )
