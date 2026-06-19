"""
Shared async HTTP client, one instance per host base URL (§2.1).

Usage:
    client = get_client("https://sports-reference.com")
    data = await client.get_json("/path", params={"season": "2020"})

Every request automatically:
  1. Waits for a rate-limit token (HostResilience.limiter)
  2. Checks the circuit breaker (HostResilience.breaker)
  3. Fires the request via httpx with retry-with-backoff on transient errors

For blocking library calls that can't accept an injected client, use the
sync context manager:
    with limit_sync("baseball-reference.com"):
        result = pybaseball.batting_stats(2020)
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx

from sports_data_mcp.resilience import (
    CircuitOpenError,
    HostResilience,
    get_host_resilience,
    retry_with_backoff,
)

logger = logging.getLogger(__name__)

_USER_AGENT = "sports-data-mcp/0.1 (+https://github.com/sports-data-mcp/sports-data-mcp)"
_DEFAULT_TIMEOUT = 20.0

_clients: dict[str, SportsHttpClient] = {}


class SportsHttpClient:
    """Async HTTP client for a single host with integrated resilience."""

    def __init__(self, base_url: str, resilience: HostResilience) -> None:
        self._base_url = base_url.rstrip("/")
        self._resilience = resilience
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"User-Agent": _USER_AGENT},
            timeout=_DEFAULT_TIMEOUT,
            follow_redirects=True,
        )

    async def get_json(self, path: str, params: dict | None = None) -> object:
        """GET `path` and return parsed JSON. Raises on HTTP errors or circuit-open."""
        await self._resilience.limiter.acquire()

        async def _do_request():
            resp = await self._client.get(path, params=params or {})
            resp.raise_for_status()
            return resp.json()

        try:
            result = await retry_with_backoff(
                _do_request,
                max_attempts=2,
                base_delay=0.5,
                max_delay=4.0,
                breaker=self._resilience.breaker,
            )
        except CircuitOpenError:
            logger.warning("Circuit breaker open for %s; fast-failing.", self._base_url)
            raise
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "HTTP %d from %s%s", exc.response.status_code, self._base_url, path
            )
            raise
        except httpx.RequestError as exc:
            logger.warning("Request error for %s%s: %s", self._base_url, path, exc)
            raise

        logger.debug("GET %s%s → OK", self._base_url, path)
        return result

    async def aclose(self) -> None:
        await self._client.aclose()


def get_client(base_url: str, rpm: int | None = None) -> SportsHttpClient:
    """Return (creating on demand) the shared SportsHttpClient for a base URL."""
    host = urlparse(base_url).netloc
    if base_url not in _clients:
        resilience = get_host_resilience(host, rpm=rpm)
        _clients[base_url] = SportsHttpClient(base_url, resilience)
    return _clients[base_url]


class _SyncLimitContext:
    """Context manager for rate-limiting blocking library calls by host."""

    def __init__(self, host: str) -> None:
        self._resilience = get_host_resilience(host)

    def __enter__(self):
        self._resilience.breaker.check()
        self._resilience.limiter.acquire_sync()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self._resilience.breaker.record_success()
        else:
            self._resilience.breaker.record_failure()
        return False


def limit_sync(host: str) -> _SyncLimitContext:
    """Use as `with limit_sync('baseball-reference.com'): pybaseball.batting_stats(...)`."""
    return _SyncLimitContext(host)
