"""
In-process single-flight coalescing per cache key (§4.4.b, §4.5.c).

When multiple concurrent callers request the same key:
  - The first caller starts the work (becomes the "worker").
  - Subsequent callers await the same asyncio.Future.
  - All callers receive the same result when the worker finishes.

On timeout (§4.5.c):
  - The waiting caller receives asyncio.TimeoutError immediately.
  - The worker coroutine is NOT cancelled — it continues to completion,
    populating the cache as normal so the next call is a cache hit.
  - A separate prefetch thread is NOT spawned (see plan revision note §4.5.c).
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)


class SingleFlight:
    """Coalesce concurrent async calls for the same key into a single execution."""

    def __init__(self) -> None:
        # key → Future[result]
        self._in_flight: dict[str, asyncio.Future[Any]] = {}

    async def call(
        self,
        key: str,
        coro_factory: Callable[[], Awaitable[Any]],
        *,
        timeout: float | None = None,
    ) -> Any:
        """
        Execute `coro_factory()` for `key`, or await an existing in-flight call.

        If `timeout` is set and we are a waiting caller (not the worker), we may
        raise asyncio.TimeoutError — but the worker continues running.

        If `timeout` is set and we are the worker, the work is not bounded by
        the timeout here; callers impose their own timeouts via this parameter.
        """
        if key in self._in_flight:
            # A worker is already running — become a waiter
            fut = self._in_flight[key]
            logger.debug("SingleFlight: coalescing onto in-flight key %r", key)
            try:
                return await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)
            except TimeoutError:
                # Caller times out; worker continues (§4.5.c)
                logger.debug(
                    "SingleFlight: caller for key %r timed out; worker continues.", key
                )
                raise

        # Become the worker
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[Any] = loop.create_future()
        self._in_flight[key] = fut
        logger.debug("SingleFlight: starting worker for key %r", key)

        try:
            result = await coro_factory()
            fut.set_result(result)
            return result
        except Exception as exc:
            fut.set_exception(exc)
            # Mark the exception as retrieved so asyncio doesn't log a spurious
            # "Future exception was never retrieved" warning when there are no
            # waiters. The worker itself re-raises below, so the error is not lost.
            fut.exception()
            raise
        finally:
            # Always release the slot so new calls can start a fresh worker
            self._in_flight.pop(key, None)
