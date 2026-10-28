from __future__ import annotations

from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.clipboard.pyperclip import PyperclipClipboard
from prompt_toolkit.filters import has_selection
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.selection import SelectionType


class ChatInput:
    """Terminal-native multiline editor with familiar clipboard behavior."""

    def __init__(self, *, input: Any = None, output: Any = None) -> None:
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

        self._session: PromptSession[str] = PromptSession(
            history=InMemoryHistory(),
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
                "<b>Ctrl+A/C/V/Z</b> select/copy/paste/undo  ·  <b>Ctrl+D</b> exit "
            ),
        )
