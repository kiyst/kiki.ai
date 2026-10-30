from kiki.capabilities import Capability
from kiki.models import ModelRouter


def test_auto_model_profile_routes_stronger_tasks(monkeypatch) -> None:
    monkeypatch.setenv("KIKI_MODEL_PERSONALITY", "kiki-voice")
    monkeypatch.setenv("KIKI_MODEL_FAST", "tiny")
    monkeypatch.setenv("KIKI_MODEL_SMART", "strong")
    router = ModelRouter("default")

    assert router.select("auto", Capability.CHAT).model == "kiki-voice"
    assert router.select("auto", Capability.CODE).model == "strong"
    assert router.select("auto", Capability.RAG).model == "kiki-voice"
    assert router.select("auto", Capability.WEATHER).model == "kiki-voice"


def test_explicit_model_profile_overrides_task(monkeypatch) -> None:
    monkeypatch.setenv("KIKI_MODEL_MAX", "largest")
    selection = ModelRouter("default").select("max", Capability.CHAT)

    assert selection.model == "largest"
    assert selection.profile == "max"
