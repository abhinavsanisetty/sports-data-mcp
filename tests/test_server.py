"""
Tests for server bootstrap resilience (§2.2, §5.4 Phase 4).

The eval harness must be able to instantiate SportsServer and call tools without
GEMINI_API_KEY set — a regression here makes the whole eval gate crash on import
of config rather than reporting a score.
"""
from __future__ import annotations

import sys

sys.path.insert(0, "src")

import pytest


@pytest.fixture
def _no_key_env(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("SPORTS_MCP_CACHE_PATH", str(tmp_path / "cache.db"))
    monkeypatch.setenv("SPORTS_MCP_ALLOW_UNSAFE_PATH", "1")
    # Reset the module-level bootstrap singletons so the fixture's env applies.
    import sports_data_mcp.server as srv

    srv._bootstrapped = False
    srv._config = None
    srv._cache = None
    srv._name_resolver = None
    srv._stat_resolver = None
    yield


def test_server_starts_without_gemini_key(_no_key_env):
    from sports_data_mcp.server import SportsServer

    server = SportsServer()
    # list_sports needs no adapter, no key, no network — must succeed.
    out = server.call_tool("list_sports", {})
    assert out["status"] == "ok"
    assert "nba" in out["sports"]


def test_unknown_sport_returns_not_implemented(_no_key_env):
    from sports_data_mcp.server import SportsServer

    server = SportsServer()
    # soccer has no adapter in Phase 4 → not_implemented, never a crash.
    out = server.call_tool("get_team_history", {"team_name": "Arsenal", "sport": "soccer"})
    assert out["status"] == "not_implemented"
