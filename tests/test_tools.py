from pathlib import Path
import json

from deskai.retrieval import TextIndex
from deskai.permissions import DESTRUCTIVE
from deskai.tools import SearchFilesArgs, ToolRegistry, ToolSpec


def test_registry_rejects_unknown_tool_and_extra_arguments(tmp_path: Path) -> None:
    registry = ToolRegistry(TextIndex(tmp_path / "index.sqlite3"))

    unknown = registry.call("run_shell", {"command": "whoami"})
    invalid = registry.call("search_files", {"query": "test", "surprise": True})

    assert unknown["status"] == "error"
    assert invalid["status"] == "error"


class FakeWeather:
    def get_weather(self, location: str, country_code: str, days: int) -> dict[str, object]:
        return {"location": location, "country_code": country_code, "days": days}


class BrokenWeather:
    def get_weather(self, location: str, country_code: str, days: int) -> dict[str, object]:
        raise KeyError("unexpected provider shape")


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
    json.dumps(invalid)


def test_tool_rejects_missing_fields_and_coercion(tmp_path: Path) -> None:
    registry = ToolRegistry(
        TextIndex(tmp_path / "index.sqlite3"), weather=FakeWeather()
    )

    missing = registry.call("get_weather", {"days": 2})
    wrong_type = registry.call("get_weather", {"location": "Boston", "days": "2"})

    assert missing["code"] == "invalid_request"
    assert wrong_type["code"] == "invalid_request"
    assert missing["retryable"] is False


def test_unexpected_tool_exception_is_contained(tmp_path: Path) -> None:
    registry = ToolRegistry(
        TextIndex(tmp_path / "index.sqlite3"), weather=BrokenWeather()
    )

    result = registry.call("get_weather", {"location": "Boston"})

    assert result["status"] == "error"
    assert result["code"] == "internal_error"
    assert "unexpected provider shape" not in result["error"]
    assert result["reference"]


def test_tool_catalog_exposes_read_only_policy(tmp_path: Path) -> None:
    registry = ToolRegistry(TextIndex(tmp_path / "index.sqlite3"))

    assert registry.catalog()["search_files"] == {
        "risk": "read_only",
        "confirmation_required": False,
        "description": "Search indexed local files and return cited excerpts.",
    }


def test_permission_policy_blocks_execution_without_approval(tmp_path: Path) -> None:
    registry = ToolRegistry(TextIndex(tmp_path / "index.sqlite3"))
    ran: list[str] = []
    registry._tools["dangerous_test"] = ToolSpec(
        SearchFilesArgs,
        lambda arguments: ran.append(arguments.query),
        "Test-only destructive tool.",
        DESTRUCTIVE,
    )

    denied = registry.call("dangerous_test", {"query": "erase"})
    allowed = registry.call("dangerous_test", {"query": "erase"}, approved=True)

    assert denied["code"] == "permission_required"
    assert denied["data"]["risk"] == "destructive"
    assert ran == ["erase"]
    assert allowed["status"] == "ok"

