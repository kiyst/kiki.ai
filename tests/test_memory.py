import pytest

from deskai.memory import MemoryStore, SensitiveMemoryError


def test_memory_round_trip_and_forget(tmp_path) -> None:
    store = MemoryStore(tmp_path / "kiki-memory.md")

    store.remember("I prefer concise explanations")
    store.remember("I prefer concise explanations")

    assert store.notes() == ["I prefer concise explanations"]
    assert "concise explanations" in store.prompt()
    assert store.forget("concise") == ["I prefer concise explanations"]
    assert store.notes() == []


def test_memories_are_numbered_and_can_be_forgotten_by_number(tmp_path) -> None:
    store = MemoryStore(tmp_path / "kiki-memory.md")
    store.remember("First preference")
    store.remember("Second preference")
    store.remember("Third preference")

    assert store.numbered() == [
        (1, "First preference"),
        (2, "Second preference"),
        (3, "Third preference"),
    ]
    assert store.forget("2") == ["Second preference"]
    assert store.numbered() == [(1, "First preference"), (2, "Third preference")]
    assert store.forget("99") == []


@pytest.mark.parametrize(
    "note",
    [
        "My password is hunter2",
        "My credit card number is 4111111111111111",
        "My phone number is 401 555 0199",
        "My API key is sk-supersecret12345",
    ],
)
def test_memory_rejects_sensitive_details(tmp_path, note) -> None:
    store = MemoryStore(tmp_path / "kiki-memory.md")

    with pytest.raises(SensitiveMemoryError):
        store.remember(note)

    assert store.notes() == []
