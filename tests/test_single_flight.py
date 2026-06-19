"""Tests for single_flight.py: coalescing, timeout-worker-continues, independent keys."""
from __future__ import annotations

import sys

sys.path.insert(0, "src")

import asyncio

import pytest

from sports_data_mcp.single_flight import SingleFlight


@pytest.mark.asyncio
async def test_coalescing_single_call_per_key():
    sf = SingleFlight()
    call_count = 0
    barrier = asyncio.Event()

    async def slow_work():
        nonlocal call_count
        call_count += 1
        await barrier.wait()
        return "result"

    # Start 3 concurrent callers for the same key
    tasks = [asyncio.create_task(sf.call("key1", slow_work)) for _ in range(3)]
    await asyncio.sleep(0)  # let tasks start
    barrier.set()

    results = await asyncio.gather(*tasks)
    assert call_count == 1, "Only one call to the factory"
    assert all(r == "result" for r in results)


@pytest.mark.asyncio
async def test_independent_keys_run_concurrently():
    sf = SingleFlight()
    started = []

    async def work(name: str):
        started.append(name)
        await asyncio.sleep(0.01)
        return name

    results = await asyncio.gather(
        sf.call("a", lambda: work("a")),
        sf.call("b", lambda: work("b")),
    )
    assert set(results) == {"a", "b"}
    assert "a" in started and "b" in started


@pytest.mark.asyncio
async def test_timeout_caller_gets_error_worker_continues():
    sf = SingleFlight()
    worker_finished = asyncio.Event()
    work_started = asyncio.Event()
    worker_result = []

    async def slow_work():
        work_started.set()
        await asyncio.sleep(0.15)
        worker_result.append("done")
        worker_finished.set()
        return "worker_result"

    # Start the worker
    worker_task = asyncio.create_task(sf.call("slow", slow_work))
    await work_started.wait()

    # Second caller times out while waiting
    with pytest.raises(asyncio.TimeoutError):
        await sf.call("slow", slow_work, timeout=0.01)

    # Worker must still finish (§4.5.c)
    await asyncio.wait_for(worker_finished.wait(), timeout=1.0)
    assert worker_result == ["done"]

    # Worker task itself should complete successfully
    result = await worker_task
    assert result == "worker_result"


@pytest.mark.asyncio
async def test_exception_propagates_to_all_waiters():
    sf = SingleFlight()
    barrier = asyncio.Event()

    async def failing_work():
        await barrier.wait()
        raise ValueError("boom")

    tasks = [asyncio.create_task(sf.call("err", failing_work)) for _ in range(3)]
    await asyncio.sleep(0)
    barrier.set()

    results = await asyncio.gather(*tasks, return_exceptions=True)
    assert all(isinstance(r, ValueError) for r in results)


@pytest.mark.asyncio
async def test_slot_released_after_completion():
    sf = SingleFlight()

    async def work():
        return 42

    r1 = await sf.call("k", work)
    r2 = await sf.call("k", work)  # new call starts fresh
    assert r1 == 42
    assert r2 == 42
    assert "k" not in sf._in_flight
