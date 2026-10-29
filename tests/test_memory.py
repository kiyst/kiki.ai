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
