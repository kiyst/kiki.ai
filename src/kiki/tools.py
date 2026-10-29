from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .providers.weather import WeatherProvider
from .permissions import READ_ONLY, ToolPolicy, requires_confirmation
from .resilience import ErrorCode, safe_error
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


@dataclass(frozen=True)
class ToolSpec:
    arguments: type[BaseModel]
    handler: Callable[[BaseModel], Any]
    description: str
    policy: ToolPolicy


class ToolRegistry:
    """Allowlisted dispatch boundary used by both CLI and future model clients."""

    def __init__(
        self,
        index: SearchBackend | None = None,
        weather: WeatherProvider | None = None,
        *,
        include_search: bool = True,
    ) -> None:
        self._tools: dict[str, ToolSpec] = {}
        if include_search:
            if index is None:
                raise ValueError("A search backend is required when search_files is enabled")
            self._tools["search_files"] = ToolSpec(
                SearchFilesArgs,
                self._search_files,
                _TOOL_DESCRIPTIONS["search_files"],
                READ_ONLY,
            )
        if weather is not None:
            self._tools["get_weather"] = ToolSpec(
                GetWeatherArgs,
                self._get_weather,
                _TOOL_DESCRIPTIONS["get_weather"],
                READ_ONLY,
            )
        self._index = index
        self._weather = weather

    def schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": spec.description,
                    "parameters": spec.arguments.model_json_schema(),
                },
            }
            for name, spec in self._tools.items()
        ]

    def catalog(self) -> dict[str, dict[str, Any]]:
        return {
            name: {
                "risk": spec.policy.risk.value,
                "confirmation_required": spec.policy.confirmation_required,
                "description": spec.description,
            }
            for name, spec in self._tools.items()
        }

    def call(
        self, name: str, arguments: dict[str, Any], *, approved: bool = False
    ) -> dict[str, Any]:
        entry = self._tools.get(name)
        if entry is None:
            return {
                "status": "error",
                "error": f"Unknown tool: {name}",
                "code": ErrorCode.INVALID_REQUEST.value,
                "retryable": False,
                "data": None,
            }
        if requires_confirmation(entry.policy) and not approved:
            return {
                "status": "error",
                "error": f"Permission is required before running {name}",
                "code": ErrorCode.PERMISSION_REQUIRED.value,
                "retryable": False,
                "data": {
                    "tool": name,
                    "risk": entry.policy.risk.value,
                },
            }
        try:
            validated = entry.arguments.model_validate(arguments)
        except ValidationError as exc:
            return {
                "status": "error",
                "error": "Invalid arguments",
                "code": ErrorCode.INVALID_REQUEST.value,
                "retryable": False,
                "details": json.loads(exc.json(include_url=False)),
                "data": None,
            }
        try:
            return {"status": "ok", "error": None, "data": entry.handler(validated)}
        except (OSError, ValueError) as exc:
            return {
                "status": "error",
                "error": str(exc),
                "code": ErrorCode.SERVICE_UNAVAILABLE.value
                if isinstance(exc, OSError)
                else ErrorCode.PROVIDER_RESPONSE.value,
                "retryable": isinstance(exc, OSError),
                "data": None,
            }
        except Exception as exc:
            # Tool boundaries never expose a traceback or take down the model loop.
            return safe_error(exc)

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

