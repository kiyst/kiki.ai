import pytest


@pytest.fixture(autouse=True)
def _no_live_danger_judge(monkeypatch):
    # The danger check asks the local model about every CHAT message; tests
    # must never reach a real model. Tests of the check give their own judge.
    monkeypatch.setattr("kiki.terminal.ollama_judge", lambda model: lambda message, earlier: "none")
