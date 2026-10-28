from pathlib import Path

from deskai.retrieval import TextIndex
from deskai.tools import ToolRegistry


def test_registry_rejects_unknown_tool_and_extra_arguments(tmp_path: Path) -> None:
    registry = ToolRegistry(TextIndex(tmp_path / "index.sqlite3"))

    unknown = registry.call("run_shell", {"command": "whoami"})
    invalid = registry.call("search_files", {"query": "test", "surprise": True})

    assert unknown["status"] == "error"
    assert invalid["status"] == "error"


class FakeWeather:
    def get_weather(self, location: str, country_code: str, days: int) -> dict[str, object]:
        return {"location": location, "country_code": country_code, "days": days}


def test_weather_tool_validates_and_normalizes_arguments(tmp_path: Path) -> None:
    registry = ToolRegistry(
        TextIndex(tmp_path / "index.sqlite3"), weather=FakeWeather()
    )

    valid = registry.call(
        "get_weather", {"location": " Boston ", "country_code": "us", "days": 2}
    )
    invalid = registry.call("get_weather", {"location": "x", "days": 20})

    assert valid["status"] == "ok"
    assert valid["data"] == {"location": "Boston", "country_code": "US", "days": 2}
    assert invalid["status"] == "error"

