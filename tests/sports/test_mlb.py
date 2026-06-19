"""
Tests for MLBAdapter (§3.33, §5.4 Phase 4).

Happy-paths use vcr to record real network calls.
Error-paths use responses/respx to mock API failures and verify fallbacks.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import httpx
import pandas as pd
import pytest
import respx
import vcr

sys.path.insert(0, "src")

import pybaseball

from sports_data_mcp.sports.mlb import MLBAdapter

_CASSETTES_DIR = Path(__file__).parent.parent / "cassettes" / "mlb"
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
    adapter = MLBAdapter()
    cassette = str(_CASSETTES_DIR / "player_stats_happy.yaml")
    with my_vcr.use_cassette(cassette):
        res = adapter.get_player_stats(player_name="Mike Trout", season="2018")

    assert res.sport == "mlb"
    assert res.query_type == "player_stats"
    assert res.entity.name == "Mike Trout"
    assert res.meta.source == "pybaseball"
    res.meta.fetched_at = 1781843534
    res.meta.latency_ms = 10
    assert res.model_dump(mode="json", by_alias=True) == snapshot


def test_get_player_game_log_happy(snapshot):
    adapter = MLBAdapter()
    cassette = str(_CASSETTES_DIR / "player_game_log_happy.yaml")
    with my_vcr.use_cassette(cassette):
        res = adapter.get_player_game_log(player_name="Shohei Ohtani", season="2023", limit=5)

    assert res.sport == "mlb"
    assert res.query_type == "player_game_log"
    assert len(res.core["games"]) == 5
    res.meta.fetched_at = 1781843534
    res.meta.latency_ms = 10
    assert res.model_dump(mode="json", by_alias=True) == snapshot


def test_get_team_stats_happy(snapshot):
    adapter = MLBAdapter()
    cassette = str(_CASSETTES_DIR / "team_stats_happy.yaml")
    with my_vcr.use_cassette(cassette):
        res = adapter.get_team_stats(team_name="Boston Red Sox", season="2018")

    assert res.sport == "mlb"
    assert res.query_type == "team_stats"
    assert res.meta.source == "pybaseball"
    res.meta.fetched_at = 1781843534
    res.meta.latency_ms = 10
    assert res.model_dump(mode="json", by_alias=True) == snapshot


def test_get_team_game_log_happy(snapshot):
    adapter = MLBAdapter()
    cassette = str(_CASSETTES_DIR / "team_game_log_happy.yaml")
    with my_vcr.use_cassette(cassette):
        res = adapter.get_team_game_log(team_name="Houston Astros", season="2017", limit=5)

    assert res.sport == "mlb"
    assert res.query_type == "team_game_log"
    assert len(res.core["games"]) == 5
    res.meta.fetched_at = 1781843534
    res.meta.latency_ms = 10
    assert res.model_dump(mode="json", by_alias=True) == snapshot


def test_get_league_leaders_happy(snapshot):
    adapter = MLBAdapter()
    cassette = str(_CASSETTES_DIR / "league_leaders_happy.yaml")
    with my_vcr.use_cassette(cassette):
        res = adapter.get_league_leaders(stat="home_runs", season="2018", limit=5)

    assert res.sport == "mlb"
    assert res.query_type == "league_leaders"
    assert len(res.core["leaders"]) == 5
    res.meta.fetched_at = 1781843534
    res.meta.latency_ms = 10
    assert res.model_dump(mode="json", by_alias=True) == snapshot


def test_get_team_history_happy(snapshot):
    adapter = MLBAdapter()
    cassette = str(_CASSETTES_DIR / "team_history_happy.yaml")
    with my_vcr.use_cassette(cassette):
        res = adapter.get_team_history(team_name="New York Yankees")

    assert res.sport == "mlb"
    assert res.query_type == "team_history"
    assert res.meta.source == "mlb_api"
    res.meta.fetched_at = 1781843534
    res.meta.latency_ms = 10
    assert res.model_dump(mode="json", by_alias=True) == snapshot


# ---------------------------------------------------------------------------
# Fallback / Error-path tests (Respx / Monkeypatch mocked)
# ---------------------------------------------------------------------------


@respx.mock
def test_get_player_stats_fallback(monkeypatch):
    # Mock pybaseball lookups to fail
    monkeypatch.setattr(
        pybaseball,
        "playerid_lookup",
        lambda *a, **kw: pd.DataFrame([{"key_mlbam": 545361, "key_bbref": "troutmi01"}]),
    )
    monkeypatch.setattr(
        pybaseball,
        "batting_stats_bref",
        lambda *a, **kw: ValueError("offline"),
    )
    monkeypatch.setattr(
        pybaseball,
        "pitching_stats_bref",
        lambda *a, **kw: ValueError("offline"),
    )

    # mlb_api fallback succeeds
    mock_data = {
        "stats": [
            {
                "splits": [
                    {
                        "stat": {
                            "gamesPlayed": 140,
                            "atBats": 470,
                            "runs": 101,
                            "hits": 147,
                            "homeRuns": 39,
                            "rbi": 79,
                            "avg": "0.312",
                            "obp": "0.460",
                            "slg": "0.628",
                            "ops": "1.088",
                        }
                    }
                ]
            }
        ]
    }
    respx.get(re.compile(r".*statsapi\.mlb\.com/api/v1/people/.*")).mock(
        return_value=httpx.Response(200, json=mock_data)
    )

    adapter = MLBAdapter()
    res = adapter.get_player_stats(player_name="Mike Trout", season="2018")

    assert res.meta.source == "mlb_api"
    assert "pybaseball" in res.meta.attempted_sources
    assert "mlb_api" in res.meta.attempted_sources
    assert res.core["home_runs"] == 39


@respx.mock
def test_player_game_log_fallback(monkeypatch):
    monkeypatch.setattr(
        pybaseball,
        "playerid_lookup",
        lambda *a, **kw: pd.DataFrame([{"key_mlbam": 660271, "key_bbref": "ohtansh01"}]),
    )

    mock_data = {
        "stats": [
            {
                "splits": [
                    {
                        "date": "2023-04-01",
                        "game": {"gamePk": 12345},
                        "opponent": {"name": "Oakland Athletics"},
                        "isWin": True,
                        "stat": {
                            "hits": 2,
                            "homeRuns": 1,
                            "rbi": 3,
                        },
                    }
                ]
            }
        ]
    }
    respx.get(re.compile(r".*statsapi\.mlb\.com/api/v1/people/.*")).mock(
        return_value=httpx.Response(200, json=mock_data)
    )

    adapter = MLBAdapter()
    res = adapter.get_player_game_log(player_name="Shohei Ohtani", season="2023")
    assert res.meta.source == "mlb_api"
    assert res.core["games"][0]["home_runs"] == 1


@respx.mock
def test_team_stats_fallback(monkeypatch):
    monkeypatch.setattr(
        pybaseball,
        "standings",
        lambda *a, **kw: ValueError("offline"),
    )
    mock_data = {
        "records": [
            {
                "teamRecords": [
                    {
                        "team": {"id": 111},
                        "gamesPlayed": 162,
                        "wins": 108,
                        "losses": 54,
                        "winningPercentage": "0.667",
                    }
                ]
            }
        ]
    }
    respx.get(re.compile(r".*statsapi\.mlb\.com/api/v1/standings.*")).mock(
        return_value=httpx.Response(200, json=mock_data)
    )

    adapter = MLBAdapter()
    res = adapter.get_team_stats(team_name="Boston Red Sox", season="2018")
    assert res.meta.source == "mlb_api"
    assert res.core["wins"] == 108


@respx.mock
def test_team_game_log_fallback(monkeypatch):
    monkeypatch.setattr(
        pybaseball,
        "schedule_and_record",
        lambda *a, **kw: ValueError("offline"),
    )
    mock_data = {
        "dates": [
            {
                "games": [
                    {
                        "gamePk": 67890,
                        "gameDate": "2017-04-03T19:00:00Z",
                        "status": {"abstractGameState": "Final"},
                        "teams": {
                            "home": {
                                "team": {"id": 117, "name": "Houston Astros"},
                                "score": 3,
                                "isWinner": True,
                            },
                            "away": {
                                "team": {"id": 136, "name": "Seattle Mariners"},
                                "score": 0,
                                "isWinner": False,
                            },
                        },
                    }
                ]
            }
        ]
    }
    respx.get(re.compile(r".*statsapi\.mlb\.com/api/v1/schedule.*")).mock(
        return_value=httpx.Response(200, json=mock_data)
    )

    adapter = MLBAdapter()
    res = adapter.get_team_game_log(team_name="Houston Astros", season="2017")
    assert res.meta.source == "mlb_api"
    assert res.core["games"][0]["runs_scored"] == 3


@respx.mock
def test_league_leaders_fallback(monkeypatch):
    monkeypatch.setattr(
        pybaseball,
        "batting_stats_bref",
        lambda *a, **kw: ValueError("offline"),
    )
    monkeypatch.setattr(
        pybaseball,
        "pitching_stats_bref",
        lambda *a, **kw: ValueError("offline"),
    )
    mock_data = {
        "leagueLeaders": [
            {
                "leaders": [
                    {
                        "rank": 1,
                        "person": {"fullName": "Mike Trout"},
                        "value": "39",
                        "team": {"name": "Los Angeles Angels"},
                    }
                ]
            }
        ]
    }
    respx.get(re.compile(r".*statsapi\.mlb\.com/api/v1/stats/leaders.*")).mock(
        return_value=httpx.Response(200, json=mock_data)
    )

    adapter = MLBAdapter()
    res = adapter.get_league_leaders(stat="home_runs", season="2018")
    assert res.meta.source == "mlb_api"
    assert res.core["leaders"][0]["player_name"] == "Mike Trout"


@respx.mock
def test_team_history_fallback_to_espn():
    # mlb_api fails
    respx.get(re.compile(r".*statsapi\.mlb\.com.*")).mock(
        return_value=httpx.Response(500)
    )

    # espn succeeds
    mock_data = {
        "core": {
            "year_founded": 1903,
            "championship_years": [1923, 1927],
            "championship_count": 2,
            "abbreviation": "NYY",
            "nickname": "Yankees",
            "city": "Bronx",
            "state": "NY",
        },
        "sport_specific": {},
    }
    respx.get(re.compile(r".*espn\.com/dummy/mlb/team_history.*")).mock(
        return_value=httpx.Response(200, json=mock_data)
    )

    adapter = MLBAdapter()
    res = adapter.get_team_history(team_name="New York Yankees")
    assert res.meta.source == "espn"
    assert res.meta.attempted_sources == ["pybaseball", "mlb_api", "espn"]
    assert res.core["year_founded"] == 1903
