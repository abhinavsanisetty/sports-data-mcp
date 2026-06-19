"""
Per-host rate limiter, circuit breaker, and retry-with-backoff (§2.1).

All primitives are keyed per host (e.g. 'sports-reference.com'), not per adapter,
so aggregate traffic across all adapters respects per-host limits.

Rate limiter: token bucket — configurable RPM (default 60 req/min for official APIs,
12 req/min for scraped hosts).

Circuit breaker: opens after N consecutive failures, half-opens after cooldown,
closes on first success in half-open.

Retry: one attempt with exponential backoff + jitter.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from enum import Enum

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CircuitOpenError(Exception):
    """Raised when the circuit breaker is OPEN and fast-fails the call."""


# ---------------------------------------------------------------------------
# Token-bucket rate limiter (per host)
# ---------------------------------------------------------------------------


class RateLimiter:
    """
    Async token-bucket rate limiter.

    Allows `rpm` requests per minute on average, with burst capacity of `burst`
    tokens (defaults to rpm // 10, minimum 1).
    """

    def __init__(self, rpm: int = 60, burst: int | None = None) -> None:
        self._rate = rpm / 60.0  # tokens per second
        self._capacity = float(burst if burst is not None else max(1, rpm // 10))
        self._tokens = self._capacity
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            self._last = now
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return
            # Need to wait for a token
            wait = (1.0 - self._tokens) / self._rate
            self._tokens = 0.0
        await asyncio.sleep(wait)

    # Sync version for wrapping blocking library calls
    def acquire_sync(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last
        self._last = now
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return
        wait = (1.0 - self._tokens) / self._rate
        self._tokens = 0.0
        time.sleep(wait)


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


class BreakerState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """
    Per-host circuit breaker.

    Opens after `failure_threshold` consecutive failures.
    Half-opens after `cooldown_sec` seconds.
    Closes (resets) on first success in HALF_OPEN.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        cooldown_sec: float = 30.0,
    ) -> None:
        self._threshold = failure_threshold
        self._cooldown = cooldown_sec
        self._failures = 0
        self._state = BreakerState.CLOSED
        self._opened_at: float | None = None

    @property
    def state(self) -> BreakerState:
        if self._state == BreakerState.OPEN:
            assert self._opened_at is not None
            if time.monotonic() - self._opened_at >= self._cooldown:
                self._state = BreakerState.HALF_OPEN
        return self._state

    def check(self) -> None:
        """Raise CircuitOpenError if the breaker is OPEN."""
        if self.state == BreakerState.OPEN:
            age = time.monotonic() - (self._opened_at or 0)
            raise CircuitOpenError(
                f"Circuit breaker OPEN (opened {age:.1f}s ago, cooldown={self._cooldown}s)"
            )

    def record_success(self) -> None:
        self._failures = 0
        self._state = BreakerState.CLOSED
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self._threshold:
            if self._state != BreakerState.OPEN:
                logger.warning(
                    "Circuit breaker opened after %d consecutive failures.", self._failures
                )
            self._state = BreakerState.OPEN
            self._opened_at = time.monotonic()


# ---------------------------------------------------------------------------
# Retry with exponential backoff + jitter
# ---------------------------------------------------------------------------


async def retry_with_backoff(
    coro_factory,
    *,
    max_attempts: int = 2,
    base_delay: float = 0.5,
    max_delay: float = 4.0,
    breaker: CircuitBreaker | None = None,
) -> object:
    """
    Call `coro_factory()` up to `max_attempts` times with exponential backoff.

    If `breaker` is provided it is checked before each attempt and updated
    on success/failure.  Raises the last exception if all attempts fail.
    """
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        if breaker is not None:
            breaker.check()  # raises CircuitOpenError immediately if open
        try:
            result = await coro_factory()
            if breaker is not None:
                breaker.record_success()
            return result
        except CircuitOpenError:
            raise
        except Exception as exc:
            last_exc = exc
            if breaker is not None:
                breaker.record_failure()
            if attempt < max_attempts - 1:
                delay = min(max_delay, base_delay * (2**attempt))
                jitter = delay * 0.25 * random.random()
                wait = delay + jitter
                logger.debug(
                    "Attempt %d/%d failed (%s); retrying in %.2fs",
                    attempt + 1,
                    max_attempts,
                    exc,
                    wait,
                )
                await asyncio.sleep(wait)
    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Per-host registry
# ---------------------------------------------------------------------------

_SCRAPED_HOSTS = {"sports-reference.com", "basketball-reference.com", "baseball-reference.com"}

# Default RPM by host category
_DEFAULT_RPM_SCRAPED = 12  # 1 req / 5 sec — polite scraping
_DEFAULT_RPM_API = 60  # 1 req / sec for official APIs


class HostResilience:
    """Container for a host's rate limiter + circuit breaker."""

    def __init__(self, host: str, rpm: int | None = None) -> None:
        default_rpm = _DEFAULT_RPM_SCRAPED if host in _SCRAPED_HOSTS else _DEFAULT_RPM_API
        self.limiter = RateLimiter(rpm=rpm if rpm is not None else default_rpm)
        self.breaker = CircuitBreaker()


_registry: dict[str, HostResilience] = {}


def get_host_resilience(host: str, rpm: int | None = None) -> HostResilience:
    """Return (creating on demand) the shared HostResilience for a given host."""
    if host not in _registry:
        _registry[host] = HostResilience(host, rpm=rpm)
    return _registry[host]
