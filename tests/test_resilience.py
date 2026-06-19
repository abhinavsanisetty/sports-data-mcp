"""Tests for resilience.py: rate limiter, circuit breaker, retry-with-backoff."""
from __future__ import annotations

import sys

sys.path.insert(0, "src")

import time
import unittest.mock as mock

import pytest

from sports_data_mcp.resilience import (
    _DEFAULT_RPM_API,
    _DEFAULT_RPM_SCRAPED,
    BreakerState,
    CircuitBreaker,
    CircuitOpenError,
    HostResilience,
    RateLimiter,
    _is_scraped_host,
    retry_with_backoff,
)

# ---------------------------------------------------------------------------
# RateLimiter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limiter_allows_burst():
    limiter = RateLimiter(rpm=600, burst=5)
    # 5 requests should complete immediately (within burst)
    start = time.monotonic()
    for _ in range(5):
        await limiter.acquire()
    elapsed = time.monotonic() - start
    assert elapsed < 0.5, f"Burst should be instant, took {elapsed:.2f}s"


@pytest.mark.asyncio
async def test_rate_limiter_throttles():
    # 1 RPM → 1 token per 60s; burst=1 so 2nd call must wait; verify sleep is called
    limiter = RateLimiter(rpm=1, burst=1)
    await limiter.acquire()  # consumes the 1 token
    waited = []

    async def fake_sleep(s: float) -> None:
        waited.append(s)

    with mock.patch("asyncio.sleep", side_effect=fake_sleep):
        await limiter.acquire()

    assert len(waited) > 0


# ---------------------------------------------------------------------------
# CircuitBreaker — state transitions
# ---------------------------------------------------------------------------


def test_breaker_starts_closed():
    cb = CircuitBreaker(failure_threshold=3, cooldown_sec=30.0)
    assert cb.state == BreakerState.CLOSED


def test_breaker_opens_after_threshold():
    cb = CircuitBreaker(failure_threshold=3, cooldown_sec=30.0)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == BreakerState.CLOSED
    cb.record_failure()
    assert cb.state == BreakerState.OPEN


def test_breaker_check_raises_when_open():
    cb = CircuitBreaker(failure_threshold=1, cooldown_sec=30.0)
    cb.record_failure()
    with pytest.raises(CircuitOpenError):
        cb.check()


def test_breaker_half_opens_after_cooldown():
    cb = CircuitBreaker(failure_threshold=1, cooldown_sec=0.01)
    cb.record_failure()
    assert cb.state == BreakerState.OPEN
    time.sleep(0.02)
    assert cb.state == BreakerState.HALF_OPEN


def test_breaker_closes_on_success_in_half_open():
    cb = CircuitBreaker(failure_threshold=1, cooldown_sec=0.01)
    cb.record_failure()
    time.sleep(0.02)
    assert cb.state == BreakerState.HALF_OPEN
    cb.record_success()
    assert cb.state == BreakerState.CLOSED


def test_breaker_reset_clears_failure_count():
    cb = CircuitBreaker(failure_threshold=5, cooldown_sec=30.0)
    cb.record_failure()
    cb.record_failure()
    cb.record_success()
    # Failures should reset — need threshold failures again to open
    cb.record_failure()
    cb.record_failure()
    assert cb.state == BreakerState.CLOSED


# ---------------------------------------------------------------------------
# retry_with_backoff
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_succeeds_on_second_attempt():
    calls = []

    async def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise ValueError("transient")
        return "ok"

    result = await retry_with_backoff(flaky, max_attempts=2, base_delay=0.01)
    assert result == "ok"
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_retry_raises_after_max_attempts():
    async def always_fails():
        raise ValueError("permanent")

    with pytest.raises(ValueError, match="permanent"):
        await retry_with_backoff(always_fails, max_attempts=2, base_delay=0.01)


@pytest.mark.asyncio
async def test_retry_stops_immediately_on_open_breaker():
    cb = CircuitBreaker(failure_threshold=1, cooldown_sec=60.0)
    cb.record_failure()  # open the breaker

    calls = []

    async def should_not_run():
        calls.append(1)
        return "ok"

    with pytest.raises(CircuitOpenError):
        await retry_with_backoff(should_not_run, max_attempts=3, base_delay=0.01, breaker=cb)
    assert len(calls) == 0  # breaker check happens before each attempt


@pytest.mark.asyncio
async def test_retry_updates_breaker_on_success():
    cb = CircuitBreaker(failure_threshold=5, cooldown_sec=30.0)
    cb.record_failure()
    cb.record_failure()

    async def ok():
        return "done"

    await retry_with_backoff(ok, max_attempts=1, base_delay=0.01, breaker=cb)
    assert cb.state == BreakerState.CLOSED
    assert cb._failures == 0


# ---------------------------------------------------------------------------
# Scraped-host classification (§2.1) — www./subdomain forms must stay polite-rate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "host",
    [
        "basketball-reference.com",
        "www.basketball-reference.com",  # the form get_client derives from the NBA fallback URL
        "baseball-reference.com",
        "sports-reference.com",
        "WWW.Basketball-Reference.COM",  # case-insensitive
    ],
)
def test_scraped_hosts_get_polite_rate(host):
    assert _is_scraped_host(host) is True
    assert HostResilience(host).limiter._rate * 60 == _DEFAULT_RPM_SCRAPED


@pytest.mark.parametrize(
    "host",
    ["stats.nba.com", "statsapi.mlb.com", "site.api.espn.com"],
)
def test_api_hosts_get_api_rate(host):
    assert _is_scraped_host(host) is False
    assert HostResilience(host).limiter._rate * 60 == _DEFAULT_RPM_API


def test_lookalike_host_not_misclassified_as_scraped():
    # An attacker-style suffix that merely contains the domain must not match.
    assert _is_scraped_host("basketball-reference.com.evil.example") is False
