"""
MLB adapter implementation (§5.4 Phase 4).

Sources: pybaseball -> mlb_api -> espn.
Normalizes data to CanonicalResult with MLBExt.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import pybaseball

from sports_data_mcp.http_client import get_client, limit_sync
from sports_data_mcp.names.resolver import register_known_entity
from sports_data_mcp.sports.base import BaseSportAdapter
from sports_data_mcp.types import CanonicalResult, Entity, MLBExt, ResultMeta

logger = logging.getLogger(__name__)

# Register all 30 MLB teams at startup for fast-path name resolution (§2.2)
_MLB_TEAMS = [
    {"full_name": "Arizona Diamondbacks", "abbreviation": "ARI", "nickname": "Diamondbacks"},
    {"full_name": "Atlanta Braves", "abbreviation": "ATL", "nickname": "Braves"},
    {"full_name": "Baltimore Orioles", "abbreviation": "BAL", "nickname": "Orioles"},
    {"full_name": "Boston Red Sox", "abbreviation": "BOS", "nickname": "Red Sox"},
    {"full_name": "Chicago White Sox", "abbreviation": "CWS", "nickname": "White Sox"},
    {"full_name": "Chicago Cubs", "abbreviation": "CHC", "nickname": "Cubs"},
    {"full_name": "Cincinnati Reds", "abbreviation": "CIN", "nickname": "Reds"},
    {"full_name": "Cleveland Guardians", "abbreviation": "CLE", "nickname": "Guardians"},
    {"full_name": "Colorado Rockies", "abbreviation": "COL", "nickname": "Rockies"},
    {"full_name": "Detroit Tigers", "abbreviation": "DET", "nickname": "Tigers"},
    {"full_name": "Houston Astros", "abbreviation": "HOU", "nickname": "Astros"},
    {"full_name": "Kansas City Royals", "abbreviation": "KC", "nickname": "Royals"},
    {"full_name": "Los Angeles Angels", "abbreviation": "LAA", "nickname": "Angels"},
    {"full_name": "Los Angeles Dodgers", "abbreviation": "LAD", "nickname": "Dodgers"},
    {"full_name": "Miami Marlins", "abbreviation": "MIA", "nickname": "Marlins"},
    {"full_name": "Milwaukee Brewers", "abbreviation": "MIL", "nickname": "Brewers"},
    {"full_name": "Minnesota Twins", "abbreviation": "MIN", "nickname": "Twins"},
    {"full_name": "New York Mets", "abbreviation": "NYM", "nickname": "Mets"},
    {"full_name": "New York Yankees", "abbreviation": "NYY", "nickname": "Yankees"},
    {"full_name": "Oakland Athletics", "abbreviation": "OAK", "nickname": "Athletics"},
    {"full_name": "Philadelphia Phillies", "abbreviation": "PHI", "nickname": "Phillies"},
    {"full_name": "Pittsburgh Pirates", "abbreviation": "PIT", "nickname": "Pirates"},
    {"full_name": "San Diego Padres", "abbreviation": "SD", "nickname": "Padres"},
    {"full_name": "San Francisco Giants", "abbreviation": "SF", "nickname": "Giants"},
    {"full_name": "Seattle Mariners", "abbreviation": "SEA", "nickname": "Mariners"},
    {"full_name": "St. Louis Cardinals", "abbreviation": "STL", "nickname": "Cardinals"},
    {"full_name": "Tampa Bay Rays", "abbreviation": "TB", "nickname": "Rays"},
    {"full_name": "Texas Rangers", "abbreviation": "TEX", "nickname": "Rangers"},
    {"full_name": "Toronto Blue Jays", "abbreviation": "TOR", "nickname": "Blue Jays"},
    {"full_name": "Washington Nationals", "abbreviation": "WSH", "nickname": "Nationals"},
]

try:
    for t in _MLB_TEAMS:
        register_known_entity(t["full_name"], "mlb", t["full_name"], "team")
        register_known_entity(t["abbreviation"], "mlb", t["full_name"], "team")
        register_known_entity(t["nickname"], "mlb", t["full_name"], "team")
    # Register historical/alternate names
    register_known_entity("Cleveland Indians", "mlb", "Cleveland Guardians", "team")
    register_known_entity("Tampa Bay Devil Rays", "mlb", "Tampa Bay Rays", "team")
    register_known_entity("Montreal Expos", "mlb", "Washington Nationals", "team")
    register_known_entity("Florida Marlins", "mlb", "Miami Marlins", "team")
    register_known_entity("CHW", "mlb", "Chicago White Sox", "team")
    register_known_entity("WAS", "mlb", "Washington Nationals", "team")
except Exception as exc:
    logger.warning("Failed to register known MLB teams during import: %s", exc)

_TEAM_TO_ID = {
    "Arizona Diamondbacks": 109,
    "Atlanta Braves": 144,
    "Baltimore Orioles": 110,
    "Boston Red Sox": 111,
    "Chicago White Sox": 145,
    "Chicago Cubs": 112,
    "Cincinnati Reds": 113,
    "Cleveland Guardians": 114,
    "Colorado Rockies": 115,
    "Detroit Tigers": 116,
    "Houston Astros": 117,
    "Kansas City Royals": 118,
    "Los Angeles Angels": 108,
    "Los Angeles Dodgers": 119,
    "Miami Marlins": 146,
    "Milwaukee Brewers": 158,
    "Minnesota Twins": 142,
    "New York Mets": 121,
    "New York Yankees": 147,
    "Oakland Athletics": 133,
    "Philadelphia Phillies": 143,
    "Pittsburgh Pirates": 134,
    "San Diego Padres": 135,
    "San Francisco Giants": 137,
    "Seattle Mariners": 136,
    "St. Louis Cardinals": 138,
    "Tampa Bay Rays": 139,
    "Texas Rangers": 140,
    "Toronto Blue Jays": 141,
    "Washington Nationals": 120,
}

_TEAM_TO_ABBREV = {
    "Arizona Diamondbacks": "ARI",
    "Atlanta Braves": "ATL",
    "Baltimore Orioles": "BAL",
    "Boston Red Sox": "BOS",
    "Chicago White Sox": "CHW",
    "Chicago Cubs": "CHC",
    "Cincinnati Reds": "CIN",
    "Cleveland Guardians": "CLE",
    "Colorado Rockies": "COL",
    "Detroit Tigers": "DET",
    "Houston Astros": "HOU",
    "Kansas City Royals": "KCR",
    "Los Angeles Angels": "LAA",
    "Los Angeles Dodgers": "LAD",
    "Miami Marlins": "MIA",
    "Milwaukee Brewers": "MIL",
    "Minnesota Twins": "MIN",
    "New York Mets": "NYM",
    "New York Yankees": "NYY",
    "Oakland Athletics": "OAK",
    "Philadelphia Phillies": "PHI",
    "Pittsburgh Pirates": "PIT",
    "San Diego Padres": "SDP",
    "San Francisco Giants": "SFG",
    "Seattle Mariners": "SEA",
    "St. Louis Cardinals": "STL",
    "Tampa Bay Rays": "TBR",
    "Texas Rangers": "TEX",
    "Toronto Blue Jays": "TOR",
    "Washington Nationals": "WSN",
}

_TEAM_CHAMPIONSHIPS = {
    "Arizona Diamondbacks": [2001],
    "Atlanta Braves": [1914, 1957, 1995, 2021],
    "Baltimore Orioles": [1966, 1970, 1983],
    "Boston Red Sox": [1903, 1912, 1915, 1916, 1918, 2004, 2007, 2013, 2018],
    "Chicago White Sox": [1906, 1917, 2005],
    "Chicago Cubs": [1907, 1908, 2016],
    "Cincinnati Reds": [1919, 1940, 1975, 1976, 1990],
    "Cleveland Guardians": [1920, 1948],
    "Colorado Rockies": [],
    "Detroit Tigers": [1935, 1945, 1968, 1984],
    "Houston Astros": [2017, 2022],
    "Kansas City Royals": [1985, 2015],
    "Los Angeles Angels": [2002],
    "Los Angeles Dodgers": [1955, 1959, 1963, 1965, 1981, 1988, 2020, 2024],
    "Miami Marlins": [1997, 2003],
    "Milwaukee Brewers": [],
    "Minnesota Twins": [1924, 1987, 1991],
    "New York Mets": [1969, 1986],
    "New York Yankees": [
        1923, 1927, 1928, 1932, 1936, 1937, 1938, 1939, 1941, 1943, 1947, 1949,
        1950, 1951, 1952, 1953, 1956, 1958, 1961, 1962, 1977, 1978, 1996, 1998,
        1999, 2000, 2009
    ],
    "Oakland Athletics": [1910, 1911, 1913, 1929, 1930, 1972, 1973, 1974, 1989],
    "Philadelphia Phillies": [1980, 2008],
    "Pittsburgh Pirates": [1909, 1925, 1960, 1971, 1979],
    "San Diego Padres": [],
    "San Francisco Giants": [1905, 1921, 1922, 1933, 1954, 2010, 2012, 2014],
    "Seattle Mariners": [],
    "St. Louis Cardinals": [1926, 1931, 1934, 1942, 1944, 1946, 1964, 1967, 1982, 2006, 2011],
    "Tampa Bay Rays": [],
    "Texas Rangers": [2023],
    "Toronto Blue Jays": [1992, 1993],
    "Washington Nationals": [2019],
}


def parse_first_last(name: str) -> tuple[str, str]:
    """Helper to parse first and last name from a full name, removing common suffixes."""
    parts = [p for p in name.strip().split() if p]
    if not parts:
        return "", ""
    suffixes = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "v"}
    if len(parts) > 1 and parts[-1].lower() in suffixes:
        parts = parts[:-1]
    if len(parts) == 1:
        return parts[0], ""
    first = parts[0]
    last = " ".join(parts[1:])
    return first, last


class MLBAdapter(BaseSportAdapter):
    """MLB adapter implementing the fallback chain for all 6 query types."""

    sources = ["pybaseball", "mlb_api", "espn"]
    sport = "mlb"

    def _get_player_id(self, player_name: str) -> int:
        """Helper to get player MLBAM ID from playerid_lookup."""
        first, last = parse_first_last(player_name)
        if not first or not last:
            raise ValueError(f"Could not parse first/last name from {player_name!r}.")
        with limit_sync("baseball-reference.com"):
            df = pybaseball.playerid_lookup(last, first)
        if df.empty:
            raise ValueError(f"Player {player_name!r} not found in playerid_lookup.")
        row = df.iloc[0]
        return int(row["key_mlbam"])

    def _get_team_id(self, team_name: str) -> int:
        """Helper to get team ID from static map."""
        if team_name in _TEAM_TO_ID:
            return _TEAM_TO_ID[team_name]
        for k, v in _TEAM_TO_ID.items():
            if k.lower() == team_name.lower() or k.split()[-1].lower() == team_name.lower():
                return v
        raise ValueError(f"Team {team_name!r} not found in static list.")

    # ------------------------------------------------------------------
    # Dispatch implementation for _fetch_from
    # ------------------------------------------------------------------

    def _fetch_from(self, source: str, query_type: str, **kwargs: Any) -> Any:
        """Dispatch to per-source methods for all 6 query types."""
        if source == "pybaseball":
            return self._fetch_pybaseball(query_type, **kwargs)
        elif source == "mlb_api":
            return self._fetch_mlb_api(query_type, **kwargs)
        elif source == "espn":
            return self._fetch_espn(query_type, **kwargs)
        else:
            raise ValueError(f"Unknown source {source!r} for MLB.")

    # ------------------------------------------------------------------
    # Source: pybaseball (Primary)
    # ------------------------------------------------------------------

    def _fetch_pybaseball(self, query_type: str, **kwargs: Any) -> Any:
        """Fetch and normalize data from pybaseball (using limit_sync)."""
        season = kwargs.get("season")
        if not season:
            raise ValueError("pybaseball requires a specific season.")
        year = int(season)
        if year < 2008:
            raise ValueError("pybaseball baseball-reference scrapers only support 2008 or later.")

        if query_type == "player_stats":
            player_name = kwargs["player_name"]
            with limit_sync("baseball-reference.com"):
                df = pybaseball.batting_stats_bref(year)
            row = df[df["Name"].str.lower() == player_name.lower()]
            if not row.empty:
                r = row.iloc[0]
                core = {
                    "games_played": int(r.get("G", 0)),
                    "at_bats": int(r.get("AB", 0)),
                    "runs": int(r.get("R", 0)),
                    "hits": int(r.get("H", 0)),
                    "home_runs": int(r.get("HR", 0)),
                    "rbi": int(r.get("RBI", 0)),
                    "batting_avg": float(r.get("BA", 0.0)),
                    "on_base_pct": float(r.get("OBP", 0.0)),
                    "slugging_pct": float(r.get("SLG", 0.0)),
                    "ops": float(r.get("OPS", 0.0)),
                }
                return {"core": core, "sport_specific": {"splits": None, "pitch_mix": None}}

            with limit_sync("baseball-reference.com"):
                df_pitch = pybaseball.pitching_stats_bref(year)
            row_pitch = df_pitch[df_pitch["Name"].str.lower() == player_name.lower()]
            if not row_pitch.empty:
                r = row_pitch.iloc[0]
                core = {
                    "games_played": int(r.get("G", 0)),
                    "wins": int(r.get("W", 0)),
                    "losses": int(r.get("L", 0)),
                    "era": float(r.get("ERA", 0.0)),
                    "strikeouts_pitching": int(r.get("SO", 0)),
                    "whip": float(r.get("WHIP", 0.0)) if "WHIP" in r else 0.0,
                    "innings_pitched": float(r.get("IP", 0.0)),
                }
                return {"core": core, "sport_specific": {"splits": None, "pitch_mix": None}}

            raise ValueError(
                f"Player {player_name} not found in batting or pitching stats for {year}."
            )

        elif query_type == "team_stats":
            team_name = kwargs["team_name"]
            with limit_sync("baseball-reference.com"):
                divisions = pybaseball.standings(year)
            for div in divisions:
                row = div[div["Tm"].str.lower() == team_name.lower()]
                if not row.empty:
                    r = row.iloc[0]
                    w = int(r.get("W", 0))
                    l_val = int(r.get("L", 0))
                    core = {
                        "games_played": w + l_val,
                        "wins": w,
                        "losses": l_val,
                        "win_pct": float(r.get("W-L%", 0.0)),
                    }
                    return {"core": core, "sport_specific": {"splits": None, "pitch_mix": None}}
            raise ValueError(f"Team {team_name} not found in standings for {year}.")

        elif query_type == "team_game_log":
            team_name = kwargs["team_name"]
            abbrev = _TEAM_TO_ABBREV.get(team_name)
            if not abbrev:
                raise ValueError(f"No abbreviation mapped for team {team_name}.")
            with limit_sync("baseball-reference.com"):
                df = pybaseball.schedule_and_record(year, abbrev)
            games = []
            for _, row in df.iterrows():
                outcome_str = str(row.get("W/L", ""))
                outcome = "W" if "W" in outcome_str else "L"
                runs = row.get("R")
                runs_all = row.get("RA")
                games.append({
                    "game_id": f"{abbrev}_{year}_{len(games)+1}",
                    "date": str(row.get("Date", "")),
                    "opponent": str(row.get("Opp", "")),
                    "outcome": outcome,
                    "runs_scored": int(runs) if str(runs).isdigit() else 0,
                    "runs_allowed": int(runs_all) if str(runs_all).isdigit() else 0,
                })
            return games

        elif query_type == "league_leaders":
            stat = kwargs["stat"].lower()
            stat_map_bat = {
                "batting_avg": "BA",
                "home_runs": "HR",
                "rbi": "RBI",
                "hits": "H",
                "runs": "R",
                "doubles": "2B",
                "triples": "3B",
                "stolen_bases": "SB",
                "caught_stealing": "CS",
                "walks": "BB",
                "strikeouts_batting": "SO",
                "hit_by_pitch": "HBP",
                "games_played": "G",
                "at_bats": "AB",
                "plate_appearances": "PA",
                "on_base_pct": "OBP",
                "slugging_pct": "SLG",
                "ops": "OPS",
            }
            stat_map_pitch = {
                "era": "ERA",
                "wins": "W",
                "losses": "L",
                "saves": "SV",
                "strikeouts_pitching": "SO",
                "walks_allowed": "BB",
                "hits_allowed": "H",
                "home_runs_allowed": "HR",
                "innings_pitched": "IP",
                "games_pitched": "G",
                "games_started": "GS",
                "whip": "WHIP",
            }

            if stat in stat_map_bat:
                col = stat_map_bat[stat]
                with limit_sync("baseball-reference.com"):
                    df = pybaseball.batting_stats_bref(year)
                df_sorted = df.dropna(subset=[col]).sort_values(by=col, ascending=False)
                leaders = []
                for rank, (_, row) in enumerate(df_sorted.iterrows(), 1):
                    leaders.append({
                        "player_name": str(row["Name"]),
                        "rank": rank,
                        "value": float(row[col]),
                        "team": str(row["Tm"]),
                    })
                return leaders

            elif stat in stat_map_pitch:
                col = stat_map_pitch[stat]
                with limit_sync("baseball-reference.com"):
                    df = pybaseball.pitching_stats_bref(year)
                asc = stat in ("era", "whip")
                df_sorted = df.dropna(subset=[col]).sort_values(by=col, ascending=asc)
                leaders = []
                for rank, (_, row) in enumerate(df_sorted.iterrows(), 1):
                    leaders.append({
                        "player_name": str(row["Name"]),
                        "rank": rank,
                        "value": float(row[col]),
                        "team": str(row["Tm"]),
                    })
                return leaders

            else:
                raise ValueError(f"Stat {stat!r} not supported for MLB league leaders.")

        else:
            raise NotImplementedError(f"Query type {query_type!r} not supported in pybaseball.")

    # ------------------------------------------------------------------
    # Source: mlb_api (Fallback 1)
    # ------------------------------------------------------------------

    def _fetch_mlb_api(self, query_type: str, **kwargs: Any) -> Any:
        """Fetch and normalize data from MLB Stats API."""
        client = get_client("https://statsapi.mlb.com")

        if query_type == "player_stats":
            player_id = kwargs["player_id"]
            season = kwargs.get("season")
            if not season:
                path = f"/api/v1/people/{player_id}/stats"
                params = {"stats": "career", "group": "hitting"}
                res = asyncio.run(client.get_json(path, params=params))
                stats_list = res.get("stats", [])
                splits = stats_list[0].get("splits", []) if stats_list else []
                if splits:
                    stat = splits[0]["stat"]
                    core = {
                        "games_played": int(stat.get("gamesPlayed", 0)),
                        "at_bats": int(stat.get("atBats", 0)),
                        "runs": int(stat.get("runs", 0)),
                        "hits": int(stat.get("hits", 0)),
                        "home_runs": int(stat.get("homeRuns", 0)),
                        "rbi": int(stat.get("rbi", 0)),
                        "batting_avg": float(stat.get("avg", 0.0)) if stat.get("avg") else 0.0,
                        "on_base_pct": float(stat.get("obp", 0.0)) if stat.get("obp") else 0.0,
                        "slugging_pct": float(stat.get("slg", 0.0)) if stat.get("slg") else 0.0,
                        "ops": float(stat.get("ops", 0.0)) if stat.get("ops") else 0.0,
                    }
                    return {"core": core, "sport_specific": {"splits": None, "pitch_mix": None}}

                params = {"stats": "career", "group": "pitching"}
                res = asyncio.run(client.get_json(path, params=params))
                stats_list = res.get("stats", [])
                splits = stats_list[0].get("splits", []) if stats_list else []
                if splits:
                    stat = splits[0]["stat"]
                    core = {
                        "games_played": int(stat.get("gamesPlayed", 0)),
                        "wins": int(stat.get("wins", 0)),
                        "losses": int(stat.get("losses", 0)),
                        "era": float(stat.get("era", 0.0)) if stat.get("era") else 0.0,
                        "strikeouts_pitching": int(stat.get("strikeOuts", 0)),
                        "whip": float(stat.get("whip", 0.0)) if stat.get("whip") else 0.0,
                        "innings_pitched": (
                            float(stat.get("inningsPitched", 0.0))
                            if stat.get("inningsPitched")
                            else 0.0
                        ),
                    }
                    return {"core": core, "sport_specific": {"splits": None, "pitch_mix": None}}
                raise ValueError("No career stats found.")

            path = f"/api/v1/people/{player_id}/stats"
            params = {"stats": "season", "season": season, "group": "hitting"}
            res = asyncio.run(client.get_json(path, params=params))
            stats_list = res.get("stats", [])
            splits = stats_list[0].get("splits", []) if stats_list else []
            if splits:
                stat = splits[0]["stat"]
                core = {
                    "games_played": int(stat.get("gamesPlayed", 0)),
                    "at_bats": int(stat.get("atBats", 0)),
                    "runs": int(stat.get("runs", 0)),
                    "hits": int(stat.get("hits", 0)),
                    "home_runs": int(stat.get("homeRuns", 0)),
                    "rbi": int(stat.get("rbi", 0)),
                    "batting_avg": float(stat.get("avg", 0.0)) if stat.get("avg") else 0.0,
                    "on_base_pct": float(stat.get("obp", 0.0)) if stat.get("obp") else 0.0,
                    "slugging_pct": float(stat.get("slg", 0.0)) if stat.get("slg") else 0.0,
                    "ops": float(stat.get("ops", 0.0)) if stat.get("ops") else 0.0,
                }
                return {"core": core, "sport_specific": {"splits": None, "pitch_mix": None}}

            params = {"stats": "season", "season": season, "group": "pitching"}
            res = asyncio.run(client.get_json(path, params=params))
            stats_list = res.get("stats", [])
            splits = stats_list[0].get("splits", []) if stats_list else []
            if splits:
                stat = splits[0]["stat"]
                core = {
                    "games_played": int(stat.get("gamesPlayed", 0)),
                    "wins": int(stat.get("wins", 0)),
                    "losses": int(stat.get("losses", 0)),
                    "era": float(stat.get("era", 0.0)) if stat.get("era") else 0.0,
                    "strikeouts_pitching": int(stat.get("strikeOuts", 0)),
                    "whip": float(stat.get("whip", 0.0)) if stat.get("whip") else 0.0,
                    "innings_pitched": (
                        float(stat.get("inningsPitched", 0.0))
                        if stat.get("inningsPitched")
                        else 0.0
                    ),
                }
                return {"core": core, "sport_specific": {"splits": None, "pitch_mix": None}}
            raise ValueError(f"No stats found for season {season}.")

        elif query_type == "player_game_log":
            player_id = kwargs["player_id"]
            season = kwargs["season"]
            path = f"/api/v1/people/{player_id}/stats"
            params = {"stats": "gameLog", "season": season, "group": "hitting"}
            res = asyncio.run(client.get_json(path, params=params))
            stats_list = res.get("stats", [])
            splits = stats_list[0].get("splits", []) if stats_list else []
            if splits:
                games = []
                for entry in splits:
                    stat = entry["stat"]
                    games.append({
                        "game_id": str(entry["game"]["gamePk"]),
                        "date": entry["date"],
                        "opponent": entry["opponent"]["name"],
                        "outcome": "W" if entry.get("isWin") else "L",
                        "hits": int(stat.get("hits", 0)),
                        "home_runs": int(stat.get("homeRuns", 0)),
                        "rbi": int(stat.get("rbi", 0)),
                    })
                return games

            params = {"stats": "gameLog", "season": season, "group": "pitching"}
            res = asyncio.run(client.get_json(path, params=params))
            stats_list = res.get("stats", [])
            splits = stats_list[0].get("splits", []) if stats_list else []
            if splits:
                games = []
                for entry in splits:
                    stat = entry["stat"]
                    games.append({
                        "game_id": str(entry["game"]["gamePk"]),
                        "date": entry["date"],
                        "opponent": entry["opponent"]["name"],
                        "outcome": "W" if entry.get("isWin") else "L",
                        "innings_pitched": (
                            float(stat.get("inningsPitched", 0.0))
                            if stat.get("inningsPitched")
                            else 0.0
                        ),
                        "strikeouts": int(stat.get("strikeOuts", 0)),
                        "earned_runs": int(stat.get("earnedRuns", 0)),
                    })
                return games
            raise ValueError(f"No game log found for season {season}.")

        elif query_type == "team_stats":
            team_id = kwargs["team_id"]
            season = kwargs["season"]
            path = "/api/v1/standings"
            params = {
                "leagueId": "103,104",
                "season": season,
                "standingsTypes": "regularSeason",
            }
            res = asyncio.run(client.get_json(path, params=params))
            for record in res.get("records", []):
                for tr in record.get("teamRecords", []):
                    if tr["team"]["id"] == team_id:
                        core = {
                            "games_played": int(tr.get("gamesPlayed", 0)),
                            "wins": int(tr.get("wins", 0)),
                            "losses": int(tr.get("losses", 0)),
                            "win_pct": float(tr.get("winningPercentage", 0.0)),
                        }
                        return {"core": core, "sport_specific": {"splits": None, "pitch_mix": None}}
            raise ValueError(f"Team ID {team_id} not found in standings.")

        elif query_type == "team_game_log":
            team_id = kwargs["team_id"]
            season = kwargs["season"]
            path = "/api/v1/schedule"
            params = {"sportId": 1, "teamId": team_id, "season": season, "gameType": "R"}
            res = asyncio.run(client.get_json(path, params=params))
            games = []
            for date_entry in res.get("dates", []):
                for g in date_entry.get("games", []):
                    if g.get("status", {}).get("abstractGameState") != "Final":
                        continue
                    home = g["teams"]["home"]
                    away = g["teams"]["away"]
                    is_home = (home["team"]["id"] == team_id)
                    my_team = home if is_home else away
                    opp_team = away if is_home else home
                    games.append({
                        "game_id": str(g["gamePk"]),
                        "date": g["gameDate"].split("T")[0],
                        "opponent": opp_team["team"]["name"],
                        "outcome": "W" if my_team.get("isWinner") else "L",
                        "runs_scored": int(my_team.get("score", 0)),
                        "runs_allowed": int(opp_team.get("score", 0)),
                    })
            return games

        elif query_type == "league_leaders":
            stat = kwargs["stat"].lower()
            season = kwargs["season"]
            stat_map = {
                "home_runs": "homeRuns",
                "batting_avg": "battingAverage",
                "rbi": "runsBattedIn",
                "hits": "hits",
                "runs": "runs",
                "era": "earnedRunAverage",
                "wins": "wins",
                "saves": "saves",
                "strikeouts_pitching": "strikeOuts",
                "whip": "walksAndHitsPerInningPitched",
            }
            cat = stat_map.get(stat, "homeRuns")
            path = "/api/v1/stats/leaders"
            params = {"leaderCategories": cat, "season": season}
            res = asyncio.run(client.get_json(path, params=params))
            leaders = []
            category_lists = res.get("leagueLeaders", [])
            if category_lists:
                leader_entries = category_lists[0].get("leaders", [])
                for entry in leader_entries:
                    leaders.append(
                        {
                            "player_name": entry["person"]["fullName"],
                            "rank": entry["rank"],
                            "value": float(entry["value"]),
                            "team": entry["team"]["name"],
                        }
                    )
            return leaders

        elif query_type == "team_history":
            team_id = kwargs["team_id"]
            team_name = kwargs["team_name"]
            path = f"/api/v1/teams/{team_id}"
            res = asyncio.run(client.get_json(path))
            t = res["teams"][0]
            championship_years = _TEAM_CHAMPIONSHIPS.get(team_name, [])
            core = {
                "year_founded": int(t.get("firstYearOfPlay", 0)) if t.get("firstYearOfPlay") else 0,
                "championship_years": championship_years,
                "championship_count": len(championship_years),
                "abbreviation": t.get("abbreviation", ""),
                "nickname": t.get("teamName", ""),
                "city": t.get("locationName", ""),
                "state": "",
            }
            return {"core": core, "sport_specific": {}}

        else:
            raise ValueError(f"Unknown query type {query_type!r} for mlb_api.")

    # ------------------------------------------------------------------
    # Source: espn (Fallback 2)
    # ------------------------------------------------------------------

    def _fetch_espn(self, query_type: str, **kwargs: Any) -> Any:
        """Mock fallback endpoint hitting ESPN API."""
        client = get_client("https://site.api.espn.com")
        path = f"/dummy/mlb/{query_type}"
        return asyncio.run(client.get_json(path, params={"args": str(kwargs)}))

    # ------------------------------------------------------------------
    # Tool Methods (Structured MCP Tool API called by StructuredDispatcher)
    # ------------------------------------------------------------------

    def get_player_stats(
        self, player_name: str, season: str | None = None, **kwargs: Any
    ) -> CanonicalResult:
        player_id = self._get_player_id(player_name)
        start_time = time.perf_counter()
        out = self._try_sources(
            "player_stats",
            player_id=player_id,
            player_name=player_name,
            season=season,
        )
        latency_ms = int((time.perf_counter() - start_time) * 1000)

        entity = Entity(
            name=player_name,
            sport="mlb",
            entity_type="player",
            canonical_id=str(player_id),
        )
        meta = ResultMeta(
            source=out["source"],
            attempted_sources=out["attempted"],
            cache_status="miss",
            fetched_at=int(time.time()),
            latency_ms=latency_ms,
            below_threshold=out["below_threshold"],
        )

        res = out["result"]
        splits = res["sport_specific"].get("splits") if "sport_specific" in res else None
        pitch_mix = res["sport_specific"].get("pitch_mix") if "sport_specific" in res else None
        sport_specific = MLBExt(splits=splits, pitch_mix=pitch_mix)

        return CanonicalResult(
            sport="mlb",
            query_type="player_stats",
            entity=entity,
            season=season,
            core=res["core"],
            sport_specific=sport_specific,
            meta=meta,
        )

    def get_player_game_log(
        self, player_name: str, season: str, limit: int = 162, **kwargs: Any
    ) -> CanonicalResult:
        player_id = self._get_player_id(player_name)
        start_time = time.perf_counter()
        out = self._try_sources(
            "player_game_log",
            player_id=player_id,
            player_name=player_name,
            season=season,
        )
        latency_ms = int((time.perf_counter() - start_time) * 1000)

        entity = Entity(
            name=player_name,
            sport="mlb",
            entity_type="player",
            canonical_id=str(player_id),
        )
        meta = ResultMeta(
            source=out["source"],
            attempted_sources=out["attempted"],
            cache_status="miss",
            fetched_at=int(time.time()),
            latency_ms=latency_ms,
            below_threshold=out["below_threshold"],
        )

        res = out["result"]
        games = res[:limit]
        core = {"games": games}
        sport_specific = MLBExt()

        return CanonicalResult(
            sport="mlb",
            query_type="player_game_log",
            entity=entity,
            season=season,
            core=core,
            sport_specific=sport_specific,
            meta=meta,
        )

    def get_team_stats(
        self, team_name: str, season: str | None = None, **kwargs: Any
    ) -> CanonicalResult:
        team_id = self._get_team_id(team_name)
        start_time = time.perf_counter()
        out = self._try_sources(
            "team_stats",
            team_id=team_id,
            team_name=team_name,
            season=season,
        )
        latency_ms = int((time.perf_counter() - start_time) * 1000)

        entity = Entity(
            name=team_name,
            sport="mlb",
            entity_type="team",
            canonical_id=str(team_id),
        )
        meta = ResultMeta(
            source=out["source"],
            attempted_sources=out["attempted"],
            cache_status="miss",
            fetched_at=int(time.time()),
            latency_ms=latency_ms,
            below_threshold=out["below_threshold"],
        )

        res = out["result"]
        splits = res["sport_specific"].get("splits") if "sport_specific" in res else None
        pitch_mix = res["sport_specific"].get("pitch_mix") if "sport_specific" in res else None
        sport_specific = MLBExt(splits=splits, pitch_mix=pitch_mix)

        return CanonicalResult(
            sport="mlb",
            query_type="team_stats",
            entity=entity,
            season=season,
            core=res["core"],
            sport_specific=sport_specific,
            meta=meta,
        )

    def get_team_game_log(
        self, team_name: str, season: str, limit: int = 162, **kwargs: Any
    ) -> CanonicalResult:
        team_id = self._get_team_id(team_name)
        start_time = time.perf_counter()
        out = self._try_sources(
            "team_game_log",
            team_id=team_id,
            team_name=team_name,
            season=season,
        )
        latency_ms = int((time.perf_counter() - start_time) * 1000)

        entity = Entity(
            name=team_name,
            sport="mlb",
            entity_type="team",
            canonical_id=str(team_id),
        )
        meta = ResultMeta(
            source=out["source"],
            attempted_sources=out["attempted"],
            cache_status="miss",
            fetched_at=int(time.time()),
            latency_ms=latency_ms,
            below_threshold=out["below_threshold"],
        )

        res = out["result"]
        games = res[:limit]
        core = {"games": games}
        sport_specific = MLBExt()

        return CanonicalResult(
            sport="mlb",
            query_type="team_game_log",
            entity=entity,
            season=season,
            core=core,
            sport_specific=sport_specific,
            meta=meta,
        )

    def get_league_leaders(
        self, stat: str, season: str | None = None, limit: int = 10, **kwargs: Any
    ) -> CanonicalResult:
        start_time = time.perf_counter()
        out = self._try_sources(
            "league_leaders",
            stat=stat,
            season=season,
        )
        latency_ms = int((time.perf_counter() - start_time) * 1000)

        entity = Entity(
            name="MLB League",
            sport="mlb",
            entity_type="team",
            canonical_id="league",
        )
        meta = ResultMeta(
            source=out["source"],
            attempted_sources=out["attempted"],
            cache_status="miss",
            fetched_at=int(time.time()),
            latency_ms=latency_ms,
            below_threshold=out["below_threshold"],
        )

        res = out["result"]
        leaders = res[:limit]
        core = {"leaders": leaders}
        sport_specific = MLBExt()

        return CanonicalResult(
            sport="mlb",
            query_type="league_leaders",
            entity=entity,
            season=season,
            core=core,
            sport_specific=sport_specific,
            meta=meta,
        )

    def get_team_history(self, team_name: str, **kwargs: Any) -> CanonicalResult:
        team_id = self._get_team_id(team_name)
        start_time = time.perf_counter()
        out = self._try_sources(
            "team_history",
            team_id=team_id,
            team_name=team_name,
        )
        latency_ms = int((time.perf_counter() - start_time) * 1000)

        entity = Entity(
            name=team_name,
            sport="mlb",
            entity_type="team",
            canonical_id=str(team_id),
        )
        meta = ResultMeta(
            source=out["source"],
            attempted_sources=out["attempted"],
            cache_status="miss",
            fetched_at=int(time.time()),
            latency_ms=latency_ms,
            below_threshold=out["below_threshold"],
        )

        res = out["result"]
        sport_specific = MLBExt()

        return CanonicalResult(
            sport="mlb",
            query_type="team_history",
            entity=entity,
            season=None,
            core=res["core"],
            sport_specific=sport_specific,
            meta=meta,
        )
