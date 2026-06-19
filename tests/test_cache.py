"""Tests for cache.py: roundtrip, clear, write guard, CACHE_VERSION isolation."""
from __future__ import annotations

import sys

sys.path.insert(0, "src")

import pytest

from sports_data_mcp.cache import Cache


@pytest.fixture
def cache(tmp_path):
    c = Cache(db_path=tmp_path / "test.db", cache_version="v1")
    yield c
    c.close()


def test_roundtrip(cache):
    result = {"points": 30.1, "assists": 5.0}
    args = {"player": "LeBron", "season": "2020"}
    cache.set("get_player_stats", args, result, query_type="player_stats")
    hit = cache.get("get_player_stats", args)
    assert hit == result


def test_miss_returns_none(cache):
    assert cache.get("get_player_stats", {"player": "nobody"}) is None


def test_args_order_independent(cache):
    result = {"pts": 25}
    cache.set("get_player_stats", {"b": 2, "a": 1}, result, query_type="player_stats")
    hit = cache.get("get_player_stats", {"a": 1, "b": 2})
    assert hit == result


def test_clear_all(cache):
    cache.set("get_player_stats", {"x": 1}, {"pts": 10}, query_type="player_stats")
    cache.set("get_team_stats", {"x": 2}, {"wins": 50}, query_type="team_stats")
    deleted = cache.clear()
    assert deleted == 2
    assert cache.get("get_player_stats", {"x": 1}) is None


def test_clear_by_sport(cache):
    cache.set("nba_get_player_stats", {"x": 1}, {"pts": 10}, query_type="player_stats")
    cache.set("mlb_get_player_stats", {"x": 2}, {"avg": 0.300}, query_type="player_stats")
    deleted = cache.clear(sport="nba")
    assert deleted == 1
    assert cache.get("mlb_get_player_stats", {"x": 2}) is not None


def test_write_guard_rejects_empty_dict(cache):
    wrote = cache.set("get_player_stats", {"x": 1}, {}, query_type="player_stats")
    assert not wrote
    assert cache.get("get_player_stats", {"x": 1}) is None


def test_write_guard_rejects_empty_list(cache):
    wrote = cache.set("get_player_game_log", {"x": 1}, [], query_type="player_game_log")
    assert not wrote


def test_write_guard_rejects_below_threshold(cache):
    result = {"data": [1, 2, 3], "_meta": {"below_threshold": True}}
    wrote = cache.set("get_player_stats", {"x": 1}, result, query_type="player_stats")
    assert not wrote


def test_write_guard_allows_meaningful_list(cache):
    result = [{"game": 1, "pts": 30}]
    wrote = cache.set("get_player_game_log", {"x": 1}, result, query_type="player_game_log")
    assert wrote


def test_cache_version_isolation(tmp_path):
    c1 = Cache(db_path=tmp_path / "cache.db", cache_version="v1")
    c2 = Cache(db_path=tmp_path / "cache.db", cache_version="v2")
    c1.set("get_player_stats", {"p": "x"}, {"pts": 20}, query_type="player_stats")
    assert c2.get("get_player_stats", {"p": "x"}) is None
    c1.close()
    c2.close()


def test_list_sports_cached_without_query_type(cache):
    result = {"nba": ["points"], "mlb": ["batting_avg"]}
    wrote = cache.set("list_sports", {}, result)
    assert wrote
    assert cache.get("list_sports", {}) == result
