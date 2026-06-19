"""
Tests for StructuredDispatcher (§5.4 Phase 4 wiring notes, §4.7 cache rule).

These cover the adapter→cache boundary that Phase 4 introduced and that had no
direct test coverage:
  - cache miss → adapter call → serialized CanonicalResult returned
  - meaningful result is written to cache; a second call is a cache hit that
    short-circuits the adapter
  - a below_threshold result (bridged into _meta) is NOT cached (§4.7)
  - an empty/non-meaningful result is NOT cached (§4.7)
"""
from __future__ import annotations

import sys

sys.path.insert(0, "src")

import pytest

from sports_data_mcp.cache import Cache
from sports_data_mcp.names.resolver import ResolvedName
from sports_data_mcp.stats.resolver import ResolvedStat
from sports_data_mcp.tools.structured import StructuredDispatcher
from sports_data_mcp.types import CanonicalResult, Entity, NBAExt, ResultMeta


class _PassthroughNameResolver:
    """Treats every name as already canonical (no Gemini, no key needed)."""

    def resolve(self, name: str, sport: str) -> ResolvedName:
        return ResolvedName(
            canonical=name,
            sport=sport,  # type: ignore[arg-type]
            entity_type="player",
            confidence="exact",
        )


class _PassthroughStatResolver:
    def resolve(self, raw: str, sport: str) -> ResolvedStat:
        return ResolvedStat(canonical=raw, sport=sport, tier="enum", raw=raw)  # type: ignore[arg-type]


class _FakeAdapter:
    """Returns a canned CanonicalResult and records how many times it was called."""

    def __init__(self, below_threshold: bool = False, core: dict | None = None) -> None:
        self.calls = 0
        self._below_threshold = below_threshold
        self._core = core if core is not None else {"points": 27.0, "rebounds": 7.0}

    def get_player_stats(
        self, player_name: str, season: str | None = None, **kw
    ) -> CanonicalResult:
        self.calls += 1
        meta = ResultMeta(
            source="nba_api",
            attempted_sources=["nba_api"],
            cache_status="miss",
            fetched_at=1,
            latency_ms=1,
            below_threshold=self._below_threshold,
        )
        return CanonicalResult(
            sport="nba",
            query_type="player_stats",
            entity=Entity(name=player_name, sport="nba", entity_type="player"),
            season=season,
            core=self._core,
            sport_specific=NBAExt(),
            meta=meta,
        )


@pytest.fixture
def cache(tmp_path):
    c = Cache(db_path=tmp_path / "test.db", cache_version="v1")
    yield c
    c.close()


def _dispatcher(adapter, cache):
    return StructuredDispatcher(
        adapter, cache, _PassthroughNameResolver(), _PassthroughStatResolver()
    )


def test_miss_then_hit_caches_meaningful_result(cache):
    adapter = _FakeAdapter()
    disp = _dispatcher(adapter, cache)
    args = {"player_name": "LeBron James", "sport": "nba", "season": "2016"}

    first = disp.call("get_player_stats", args)
    assert first["status"] == "ok"
    assert first["core"]["points"] == 27.0
    assert adapter.calls == 1

    # Second identical call must hit cache and NOT re-invoke the adapter.
    second = disp.call("get_player_stats", args)
    assert adapter.calls == 1, "cache hit should short-circuit the adapter"
    assert second["core"]["points"] == 27.0


def test_below_threshold_result_is_not_cached(cache):
    """§5.4 wiring note 2 + §4.7: below_threshold bridged into _meta blocks caching."""
    adapter = _FakeAdapter(below_threshold=True)
    disp = _dispatcher(adapter, cache)
    args = {"player_name": "Obscure Player", "sport": "nba", "season": "2016"}

    disp.call("get_player_stats", args)
    # Nothing should have been written, so a second call re-invokes the adapter.
    disp.call("get_player_stats", args)
    assert adapter.calls == 2, "below_threshold result must not be cached"


def test_empty_core_is_not_cached(cache):
    """§4.7: a result whose core has no numeric stats is not meaningful."""
    adapter = _FakeAdapter(core={"note": "no data"})
    disp = _dispatcher(adapter, cache)
    args = {"player_name": "Empty Guy", "sport": "nba", "season": "2016"}

    disp.call("get_player_stats", args)
    disp.call("get_player_stats", args)
    assert adapter.calls == 2, "non-meaningful result must not be cached"


def test_missing_adapter_method_returns_error(cache):
    disp = _dispatcher(_FakeAdapter(), cache)
    out = disp.call("get_team_history", {"team_name": "Lakers", "sport": "nba"})
    assert out["status"] == "error"
    assert "team_history" in out["error"]
