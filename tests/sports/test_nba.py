"""
Tests for NBAAdapter (§3.33, §5.4 Phase 4).

Happy-paths use vcr to record real network calls.
Error-paths use responses to mock API failures and verify fallbacks.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import httpx
import pytest
import responses
import respx
import vcr

sys.path.insert(0, "src")

from sports_data_mcp.sports.nba import NBAAdapter

_CASSETTES_DIR = Path(__file__).parent.parent / "cassettes" / "nba"
_CASSETTES_DIR.mkdir(parents=True, exist_ok=True)

my_vcr = vcr.VCR(
    filter_query_parameters=["key"],
    record_mode="once",
    match_on=["method", "host", "path"],
)


@pytest.fixture(autouse=True)
def reset_resilience_registry():
    from sports_data_mcp.http_client import _clients
    from sports_data_mcp.resilience import _registry
    _registry.clear()
    _clients.clear()


# ---------------------------------------------------------------------------
# Happy path tests (VCR recorded)
# ---------------------------------------------------------------------------


def test_get_player_stats_happy(snapshot):
    adapter = NBAAdapter()
    cassette = str(_CASSETTES_DIR / "player_stats_happy.yaml")
    with my_vcr.use_cassette(cassette):
        res = adapter.get_player_stats(player_name="LeBron James", season="2012-13")

    assert res.sport == "nba"
    assert res.query_type == "player_stats"
    assert res.entity.name == "LeBron James"
    assert res.meta.source == "nba_api"
    res.meta.fetched_at = 1781843534
    res.meta.latency_ms = 10
    assert res.model_dump(mode="json", by_alias=True) == snapshot


def test_get_player_game_log_happy(snapshot):
    adapter = NBAAdapter()
    cassette = str(_CASSETTES_DIR / "player_game_log_happy.yaml")
    with my_vcr.use_cassette(cassette):
        res = adapter.get_player_game_log(player_name="Stephen Curry", season="2015-16", limit=5)

    assert res.sport == "nba"
    assert res.query_type == "player_game_log"
    assert len(res.core["games"]) == 5
    res.meta.fetched_at = 1781843534
    res.meta.latency_ms = 10
    assert res.model_dump(mode="json", by_alias=True) == snapshot


def test_get_team_stats_happy(snapshot):
    adapter = NBAAdapter()
    cassette = str(_CASSETTES_DIR / "team_stats_happy.yaml")
    with my_vcr.use_cassette(cassette):
        res = adapter.get_team_stats(team_name="Golden State Warriors", season="2015-16")

    assert res.sport == "nba"
    assert res.query_type == "team_stats"
    assert res.meta.source == "nba_api"
    res.meta.fetched_at = 1781843534
    res.meta.latency_ms = 10
    assert res.model_dump(mode="json", by_alias=True) == snapshot


def test_get_team_game_log_happy(snapshot):
    adapter = NBAAdapter()
    cassette = str(_CASSETTES_DIR / "team_game_log_happy.yaml")
    with my_vcr.use_cassette(cassette):
        res = adapter.get_team_game_log(team_name="Chicago Bulls", season="1995-96", limit=5)

    assert res.sport == "nba"
    assert res.query_type == "team_game_log"
    assert len(res.core["games"]) == 5
    res.meta.fetched_at = 1781843534
    res.meta.latency_ms = 10
    assert res.model_dump(mode="json", by_alias=True) == snapshot


def test_get_league_leaders_happy(snapshot):
    adapter = NBAAdapter()
    cassette = str(_CASSETTES_DIR / "league_leaders_happy.yaml")
    with my_vcr.use_cassette(cassette):
        res = adapter.get_league_leaders(stat="points", season="2022-23", limit=5)

    assert res.sport == "nba"
    assert res.query_type == "league_leaders"
    assert len(res.core["leaders"]) == 5
    res.meta.fetched_at = 1781843534
    res.meta.latency_ms = 10
    assert res.model_dump(mode="json", by_alias=True) == snapshot


def test_get_team_history_happy(snapshot):
    adapter = NBAAdapter()
    cassette = str(_CASSETTES_DIR / "team_history_happy.yaml")
    with my_vcr.use_cassette(cassette):
        res = adapter.get_team_history(team_name="Los Angeles Lakers")

    assert res.sport == "nba"
    assert res.query_type == "team_history"
    assert res.meta.source == "nba_api"
    res.meta.fetched_at = 1781843534
    res.meta.latency_ms = 10
    assert res.model_dump(mode="json", by_alias=True) == snapshot


# ---------------------------------------------------------------------------
# Fallback / Error-path tests (Responses mocked)
# ---------------------------------------------------------------------------


@responses.activate
@respx.mock
def test_get_player_stats_fallback():
    # nba_api fails
    responses.add(responses.GET, url=re.compile(r".*stats\.nba\.com.*"), status=500)

    # sportsreference fallback succeeds
    mock_data = {
        "core": {
            "games_played": 82,
            "points": 27.2,
            "rebounds": 7.4,
            "assists": 7.2,
            "steals": 1.6,
            "blocks": 0.8,
        },
        "sport_specific": {
            "advanced": {"true_shooting_pct": 0.58},
            "on_off": None,
        },
    }
    respx.get(re.compile(r".*basketball-reference\.com/dummy/nba/player_stats.*")).mock(
        return_value=httpx.Response(200, json=mock_data)
    )

    adapter = NBAAdapter()
    res = adapter.get_player_stats(player_name="LeBron James", season="2012-13")

    assert res.meta.source == "sportsreference"
    assert "nba_api" in res.meta.attempted_sources
    assert "sportsreference" in res.meta.attempted_sources
    assert res.core["points"] == 27.2


@responses.activate
@respx.mock
def test_player_game_log_fallback():
    responses.add(responses.GET, url=re.compile(r".*stats\.nba\.com.*"), status=500)
    mock_data = [
        {
            "game_id": "1",
            "date": "2015-10-27",
            "opponent": "NOP",
            "points": 30,
            "rebounds": 5,
            "assists": 6,
            "steals": 1,
            "blocks": 0,
            "minutes": "35:00",
        }
    ]
    respx.get(re.compile(r".*basketball-reference\.com/dummy/nba/player_game_log.*")).mock(
        return_value=httpx.Response(200, json=mock_data)
    )

    adapter = NBAAdapter()
    res = adapter.get_player_game_log(player_name="Stephen Curry", season="2015-16")
    assert res.meta.source == "sportsreference"
    assert res.core["games"][0]["points"] == 30


@responses.activate
@respx.mock
def test_team_stats_fallback():
    responses.add(responses.GET, url=re.compile(r".*stats\.nba\.com.*"), status=500)
    mock_data = {
        "core": {
            "games_played": 82,
            "wins": 73,
            "losses": 9,
            "win_pct": 0.890,
            "points": 114.9,
            "rebounds": 46.2,
            "assists": 28.9,
        },
        "sport_specific": {"advanced": {}, "on_off": None},
    }
    respx.get(re.compile(r".*basketball-reference\.com/dummy/nba/team_stats.*")).mock(
        return_value=httpx.Response(200, json=mock_data)
    )

    adapter = NBAAdapter()
    res = adapter.get_team_stats(team_name="Golden State Warriors", season="2015-16")
    assert res.meta.source == "sportsreference"
    assert res.core["wins"] == 73


@responses.activate
@respx.mock
def test_team_game_log_fallback():
    responses.add(responses.GET, url=re.compile(r".*stats\.nba\.com.*"), status=500)
    mock_data = [
        {
            "game_id": "1",
            "date": "1995-11-03",
            "opponent": "CHA",
            "outcome": "W",
            "points": 105,
            "rebounds": 40,
            "assists": 25,
        }
    ]
    respx.get(re.compile(r".*basketball-reference\.com/dummy/nba/team_game_log.*")).mock(
        return_value=httpx.Response(200, json=mock_data)
    )

    adapter = NBAAdapter()
    res = adapter.get_team_game_log(team_name="Chicago Bulls", season="1995-96")
    assert res.meta.source == "sportsreference"
    assert res.core["games"][0]["points"] == 105


@responses.activate
@respx.mock
def test_league_leaders_fallback():
    responses.add(responses.GET, url=re.compile(r".*stats\.nba\.com.*"), status=500)
    mock_data = [{"player_name": "Joel Embiid", "rank": 1, "value": 33.1, "team": "PHI"}]
    respx.get(re.compile(r".*basketball-reference\.com/dummy/nba/league_leaders.*")).mock(
        return_value=httpx.Response(200, json=mock_data)
    )

    adapter = NBAAdapter()
    res = adapter.get_league_leaders(stat="points", season="2022-23")
    assert res.meta.source == "sportsreference"
    assert res.core["leaders"][0]["player_name"] == "Joel Embiid"


@responses.activate
@respx.mock
def test_team_history_fallback_to_espn():
    responses.add(responses.GET, url=re.compile(r".*stats\.nba\.com.*"), status=500)
    respx.get(re.compile(r".*basketball-reference\.com.*")).mock(
        return_value=httpx.Response(500)
    )

    mock_data = {
        "core": {
            "year_founded": 1946,
            "championship_years": [1957, 1959],
            "championship_count": 2,
            "abbreviation": "BOS",
            "nickname": "Celtics",
            "city": "Boston",
            "state": "Massachusetts",
        },
        "sport_specific": {},
    }
    respx.get(re.compile(r".*espn\.com/dummy/nba/team_history.*")).mock(
        return_value=httpx.Response(200, json=mock_data)
    )

    adapter = NBAAdapter()
    res = adapter.get_team_history(team_name="Boston Celtics")
    assert res.meta.source == "espn"
    assert res.meta.attempted_sources == ["nba_api", "sportsreference", "espn"]
    assert res.core["year_founded"] == 1946

