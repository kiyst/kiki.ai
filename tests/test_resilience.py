import pytest

from kiki.resilience import CircuitBreaker, CircuitOpenError


def test_circuit_breaker_opens_after_repeated_failures() -> None:
    breaker = CircuitBreaker("test service", failure_threshold=2, recovery_seconds=60)

    breaker.failure()
    breaker.allow()
    breaker.failure()

    with pytest.raises(CircuitOpenError):
        breaker.allow()
    assert breaker.state == "open"


def test_circuit_breaker_resets_after_success() -> None:
    breaker = CircuitBreaker("test service", failure_threshold=1)
    breaker.failure()
    breaker.success()

    breaker.allow()

    assert breaker.state == "closed"
