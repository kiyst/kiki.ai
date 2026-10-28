from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .providers.weather import WeatherProvider
from .retrieval import SearchResult, TextIndex


class SearchBackend(Protocol):
    def search(self, query: str, limit: int = 5) -> list[SearchResult]: ...


class SearchFilesArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=20)


class GetWeatherArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    location: str = Field(min_length=2, max_length=120)
    country_code: str = Field(default="US")
    days: int = Field(default=3, ge=1, le=7)

    @field_validator("location")
    @classmethod
    def validate_location(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("location must contain at least two visible characters")
        return value

    @field_validator("country_code")
    @classmethod
    def validate_country_code(cls, value: str) -> str:
        value = value.strip().upper()
        if len(value) != 2 or not value.isalpha():
            raise ValueError("country_code must be a two-letter ISO country code")
        return value


class ToolRegistry:
    """Allowlisted dispatch boundary used by both CLI and future model clients."""

    def __init__(
        self,
        index: SearchBackend | None = None,
        weather: WeatherProvider | None = None,
        *,
        include_search: bool = True,
    ) -> None:
        self._tools: dict[str, tuple[type[BaseModel], Callable[[BaseModel], Any]]] = {}
        if include_search:
            if index is None:
                raise ValueError("A search backend is required when search_files is enabled")
            self._tools["search_files"] = (SearchFilesArgs, self._search_files)
        if weather is not None:
            self._tools["get_weather"] = (GetWeatherArgs, self._get_weather)
        self._index = index
        self._weather = weather

    def schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": _TOOL_DESCRIPTIONS[name],
                    "parameters": model.model_json_schema(),
                },
            }
            for name, (model, _) in self._tools.items()
        ]

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        entry = self._tools.get(name)
        if entry is None:
            return {"status": "error", "error": f"Unknown tool: {name}", "data": None}
        model, handler = entry
        try:
            validated = model.model_validate(arguments)
        except ValidationError as exc:
            return {"status": "error", "error": "Invalid arguments", "details": exc.errors(), "data": None}
        try:
            return {"status": "ok", "error": None, "data": handler(validated)}
        except (OSError, ValueError) as exc:
            return {"status": "error", "error": str(exc), "data": None}

    def _search_files(self, arguments: BaseModel) -> list[dict[str, Any]]:
        assert isinstance(arguments, SearchFilesArgs)
        assert self._index is not None
        return [result.to_dict() for result in self._index.search(arguments.query, arguments.limit)]

    def _get_weather(self, arguments: BaseModel) -> dict[str, Any]:
        assert isinstance(arguments, GetWeatherArgs)
        assert self._weather is not None
        return self._weather.get_weather(
            arguments.location, arguments.country_code, arguments.days
        )


_TOOL_DESCRIPTIONS = {
    "search_files": "Search indexed local files and return cited excerpts.",
    "get_weather": (
        "Get current conditions and a short forecast for a city or postal code. "
        "Use a specific City, State when a location may be ambiguous."
    ),
}

