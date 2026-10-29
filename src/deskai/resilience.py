from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from time import monotonic
from typing import Any
from uuid import uuid4


class ErrorCode(StrEnum):
    INVALID_REQUEST = "invalid_request"
    PERMISSION_REQUIRED = "permission_required"
    TOOL_CALL_FORMAT = "tool_call_format"
    SERVICE_UNAVAILABLE = "service_unavailable"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    PROVIDER_RESPONSE = "provider_response"
    MODEL_RESPONSE = "model_response"
    INDEX_UNAVAILABLE = "index_unavailable"
    INTERNAL_ERROR = "internal_error"


class DeskAIError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: ErrorCode,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.details = details or {}
        self.reference = uuid4().hex[:8]

    def payload(self) -> dict[str, Any]:
        return {
            "status": "error",
            "error": str(self),
            "code": self.code.value,
            "retryable": self.retryable,
            "reference": self.reference,
            "data": None,
        }


class CircuitOpenError(DeskAIError):
    def __init__(self, service: str) -> None:
        super().__init__(
            f"{service} is temporarily paused after repeated failures; try again shortly",
            code=ErrorCode.SERVICE_UNAVAILABLE,
            retryable=True,
        )


@dataclass
class CircuitBreaker:
    service: str
    failure_threshold: int = 3
    recovery_seconds: float = 30.0
    failures: int = 0
    opened_at: float | None = None

    def allow(self) -> None:
        if self.opened_at is None:
            return
        if monotonic() - self.opened_at >= self.recovery_seconds:
            self.opened_at = None
            self.failures = 0
            return
        raise CircuitOpenError(self.service)

    def success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def failure(self) -> None:
        self.failures += 1
        if self.failures >= self.failure_threshold:
            self.opened_at = monotonic()

    @property
    def state(self) -> str:
        if self.opened_at is None:
            return "closed"
        if monotonic() - self.opened_at >= self.recovery_seconds:
            return "half-open"
        return "open"


def safe_error(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, DeskAIError):
        return exc.payload()
    if isinstance(exc, ValueError):
        error = DeskAIError(
            str(exc), code=ErrorCode.INVALID_REQUEST, retryable=False
        )
        return error.payload()
    if isinstance(exc, OSError):
        error = DeskAIError(
            str(exc), code=ErrorCode.SERVICE_UNAVAILABLE, retryable=True
        )
        return error.payload()
    reference = uuid4().hex[:8]
    return {
        "status": "error",
        "error": "An unexpected internal error occurred",
        "code": ErrorCode.INTERNAL_ERROR.value,
        "retryable": False,
        "reference": reference,
        "data": None,
    }
