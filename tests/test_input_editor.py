from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document
from prompt_toolkit.history import FileHistory
from prompt_toolkit.output import DummyOutput

from deskai.input_editor import ChatInput


def test_editor_buffer_preserves_multiline_paste() -> None:
    with create_pipe_input() as pipe:
        editor = ChatInput(input=pipe, output=DummyOutput())
        assert editor._session.multiline is True
        assert editor._session.mouse_support is False


def test_editor_registers_copy_paste_and_select_all_shortcuts() -> None:
    with create_pipe_input() as pipe:
        editor = ChatInput(input=pipe, output=DummyOutput())
        registered = {
            tuple(str(key) for key in binding.keys)
            for binding in editor._session.app.key_bindings.bindings
        }

    assert ("Keys.ControlA",) in registered
    assert ("Keys.ControlC",) in registered
    assert ("Keys.ControlV",) in registered


def test_editor_uses_persistent_history_and_completes_commands(tmp_path) -> None:
    with create_pipe_input() as pipe:
        editor = ChatInput(
            input=pipe,
            output=DummyOutput(),
            history_path=tmp_path / "history",
            commands=("/copy", "/clear"),
        )
        completions = list(
            editor._session.completer.get_completions(
                Document("/co", cursor_position=3), CompleteEvent()
            )
        )

    assert isinstance(editor._session.history, FileHistory)
    assert [completion.text for completion in completions] == ["/copy"]
