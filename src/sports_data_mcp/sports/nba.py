"""
NBA adapter implementation (§5.4 Phase 4).

Sources: nba_api -> sportsreference -> espn.
Normalizes data to CanonicalResult with NBAExt.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from nba_api.stats.endpoints import (
    leagueleaders,
    playercareerstats,
    playergamelog,
    teamdashboardbygeneralsplits,
    teamdetails,
    teamgamelog,
)
from nba_api.stats.static import players as static_players
from nba_api.stats.static import teams as static_teams

from sports_data_mcp.http_client import get_client, limit_sync
from sports_data_mcp.names.resolver import register_known_entity
from sports_data_mcp.sports.base import BaseSportAdapter
from sports_data_mcp.types import CanonicalResult, Entity, NBAExt, ResultMeta

logger = logging.getLogger(__name__)

# Register all 30 NBA teams at startup for fast-path name resolution (§2.2)
try:
    for t in static_teams.get_teams():
        register_known_entity(t["full_name"], "nba", t["full_name"], "team")
        register_known_entity(t["abbreviation"], "nba", t["full_name"], "team")
        register_known_entity(t["nickname"], "nba", t["full_name"], "team")
except Exception as exc:
    logger.warning("Failed to register known NBA teams during import: %s", exc)


def normalize_season(season: str | None) -> str | None:
    """Normalize season to 'YYYY-YY' format expected by nba_api (e.g. '2016' -> '2016-17')."""
    if not season:
        return None
    season = season.strip()
    if len(season) == 4 and season.isdigit():
        year = int(season)
        next_year_short = str(year + 1)[-2:]
        return f"{year}-{next_year_short}"
    return season


class NBAAdapter(BaseSportAdapter):
    """NBA adapter implementing the fallback chain for all 6 query types."""

    sources = ["nba_api", "sportsreference", "espn"]
    sport = "nba"

    def _get_player_id(self, player_name: str) -> int:
        """Helper to get player ID from static player list."""
        matches = static_players.find_players_by_full_name(player_name)
        if not matches:
            raise ValueError(f"Player {player_name!r} not found in static list.")
        return matches[0]["id"]

    def _get_team_id(self, team_name: str) -> int:
        """Helper to get team ID from static team list."""
        matches = static_teams.find_teams_by_full_name(team_name)
        if not matches:
            raise ValueError(f"Team {team_name!r} not found in static list.")
        return matches[0]["id"]

    # ------------------------------------------------------------------
    # Dispatch implementation for _fetch_from
    # ------------------------------------------------------------------

    def _fetch_from(self, source: str, query_type: str, **kwargs: Any) -> Any:
        """Dispatch to per-source methods for all 6 query types."""
        if source == "nba_api":
            return self._fetch_nba_api(query_type, **kwargs)
        elif source == "sportsreference":
            return self._fetch_sportsreference(query_type, **kwargs)
        elif source == "espn":
            return self._fetch_espn(query_type, **kwargs)
        else:
            raise ValueError(f"Unknown source {source!r} for NBA.")

    # ------------------------------------------------------------------
    # Source: nba_api (Primary)
    # ------------------------------------------------------------------

    def _fetch_nba_api(self, query_type: str, **kwargs: Any) -> Any:
        """Fetch and normalize data from nba_api (using limit_sync)."""
        if query_type == "player_stats":
            with limit_sync("stats.nba.com"):
                career = playercareerstats.PlayerCareerStats(player_id=kwargs["player_id"])
            df_seasons = career.get_data_frames()[0]
            df_career = career.get_data_frames()[1]

            season = kwargs.get("season")
            if season:
                norm_season = normalize_season(season)
                match = df_seasons[df_seasons["SEASON_ID"] == norm_season]
                if match.empty:
                    raise ValueError(f"Season {season} not found for player.")
                row = match.iloc[0]
            else:
                if df_career.empty:
                    raise ValueError("No career stats found.")
                row = df_career.iloc[0]

            core = {
                "games_played": int(row.get("GP", 0)),
                "points": float(row.get("PTS", 0.0)),
                "rebounds": float(row.get("REB", 0.0)),
                "assists": float(row.get("AST", 0.0)),
                "steals": float(row.get("STL", 0.0)),
                "blocks": float(row.get("BLK", 0.0)),
            }
            # Advanced TS% calculation
            pts = float(row.get("PTS", 0.0))
            fga = float(row.get("FGA", 0.0))
            fta = float(row.get("FTA", 0.0))
            denom = 2.0 * (fga + 0.44 * fta)
            ts_pct = pts / denom if denom > 0 else 0.0
            sport_specific = {
                "advanced": {"true_shooting_pct": round(ts_pct, 3)},
                "on_off": None,
            }
            return {"core": core, "sport_specific": sport_specific}

        elif query_type == "player_game_log":
            with limit_sync("stats.nba.com"):
                log = playergamelog.PlayerGameLog(
                    player_id=kwargs["player_id"],
                    season=normalize_season(kwargs["season"]),
                )
            df = log.get_data_frames()[0]
            games = []
            for _, row in df.iterrows():
                games.append(
                    {
                        "game_id": str(row["Game_ID"]),
                        "date": str(row["GAME_DATE"]),
                        "opponent": str(row["MATCHUP"]),
                        "points": int(row["PTS"]),
                        "rebounds": int(row["REB"]),
                        "assists": int(row["AST"]),
                        "steals": int(row["STL"]),
                        "blocks": int(row["BLK"]),
                        "minutes": str(row["MIN"]),
                    }
                )
            return games

        elif query_type == "team_stats":
            with limit_sync("stats.nba.com"):
                dashboard = teamdashboardbygeneralsplits.TeamDashboardByGeneralSplits(
                    team_id=kwargs["team_id"],
                    season=normalize_season(kwargs.get("season")),
                )
            df = dashboard.get_data_frames()[0]
            if df.empty:
                raise ValueError("No stats found for team.")
            row = df.iloc[0]

            core = {
                "games_played": int(row.get("GP", 0)),
                "wins": int(row.get("W", 0)),
                "losses": int(row.get("L", 0)),
                "win_pct": float(row.get("W_PCT", 0.0)),
                "points": float(row.get("PTS", 0.0)),
                "rebounds": float(row.get("REB", 0.0)),
                "assists": float(row.get("AST", 0.0)),
            }
            sport_specific = {
                "advanced": {
                    "net_rating": (
                        float(row.get("NET_RATING", 0.0)) if "NET_RATING" in row else None
                    ),
                    "offensive_rating": (
                        float(row.get("OFF_RATING", 0.0)) if "OFF_RATING" in row else None
                    ),
                    "defensive_rating": (
                        float(row.get("DEF_RATING", 0.0)) if "DEF_RATING" in row else None
                    ),
                },
                "on_off": None,
            }
            return {"core": core, "sport_specific": sport_specific}

        elif query_type == "team_game_log":
            with limit_sync("stats.nba.com"):
                log = teamgamelog.TeamGameLog(
                    team_id=kwargs["team_id"],
                    season=normalize_season(kwargs["season"]),
                )
            df = log.get_data_frames()[0]
            games = []
            for _, row in df.iterrows():
                games.append(
                    {
                        "game_id": str(row["Game_ID"]),
                        "date": str(row["GAME_DATE"]),
                        "opponent": str(row["MATCHUP"]),
                        "outcome": str(row["WL"]),
                        "points": int(row["PTS"]),
                        "rebounds": int(row["REB"]),
                        "assists": int(row["AST"]),
                    }
                )
            return games

        elif query_type == "league_leaders":
            stat_map = {
                "points": "PTS",
                "rebounds": "REB",
                "assists": "AST",
                "steals": "STL",
                "blocks": "BLK",
            }
            nba_stat = stat_map.get(kwargs["stat"].lower(), "PTS")
            with limit_sync("stats.nba.com"):
                leaders = leagueleaders.LeagueLeaders(
                    season=normalize_season(kwargs.get("season")),
                    stat_category_abbreviation=nba_stat,
                )
            df = leaders.get_data_frames()[0]
            leaders_list = []
            for _, row in df.iterrows():
                leaders_list.append(
                    {
                        "player_name": str(row["PLAYER"]),
                        "rank": int(row["RANK"]),
                        "value": float(row[nba_stat]),
                        "team": str(row["TEAM"]),
                    }
                )
            return leaders_list

        elif query_type == "team_history":
            with limit_sync("stats.nba.com"):
                details = teamdetails.TeamDetails(team_id=kwargs["team_id"])
            df_details = details.get_data_frames()[0]

            if df_details.empty:
                raise ValueError(f"No details found for team ID {kwargs['team_id']}.")
            row = df_details.iloc[0]

            championship_years = []
            dfs = details.get_data_frames()
            if len(dfs) > 3:
                df_championships = dfs[3]
                if not df_championships.empty and "YEARAWARDED" in df_championships:
                    championship_years = [
                        int(y) for y in df_championships["YEARAWARDED"].dropna()
                    ]

            core = {
                "year_founded": int(row.get("YEARFOUNDED", 0)),
                "championship_years": championship_years,
                "championship_count": len(championship_years),
                "abbreviation": str(row.get("ABBREVIATION", "")),
                "nickname": str(row.get("NICKNAME", "")),
                "city": str(row.get("CITY", "")),
                "state": str(row.get("STATE", "")),
            }
            return {"core": core, "sport_specific": {}}

        else:
            raise NotImplementedError(f"Query type {query_type!r} not supported in nba_api.")

    # ------------------------------------------------------------------
    # Source: sportsreference (Fallback 1)
    # ------------------------------------------------------------------

    def _fetch_sportsreference(self, query_type: str, **kwargs: Any) -> Any:
        """Mock fallback endpoint hitting sports-reference.com domain."""
        client = get_client("https://www.basketball-reference.com")
        path = f"/dummy/nba/{query_type}"
        # Run the async get_json synchronously inside this blocking call
        return asyncio.run(client.get_json(path, params={"args": str(kwargs)}))

    # ------------------------------------------------------------------
    # Source: espn (Fallback 2)
    # ------------------------------------------------------------------

    def _fetch_espn(self, query_type: str, **kwargs: Any) -> Any:
        """Mock fallback endpoint hitting ESPN API."""
        client = get_client("https://site.api.espn.com")
        path = f"/dummy/nba/{query_type}"
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
            sport="nba",
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
        adv = res["sport_specific"].get("advanced") if "sport_specific" in res else None
        oo = res["sport_specific"].get("on_off") if "sport_specific" in res else None
        sport_specific = NBAExt(advanced=adv, on_off=oo)

        return CanonicalResult(
            sport="nba",
            query_type="player_stats",
            entity=entity,
            season=season,
            core=res["core"],
            sport_specific=sport_specific,
            meta=meta,
        )

    def get_player_game_log(
        self, player_name: str, season: str, limit: int = 82, **kwargs: Any
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
            sport="nba",
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
        sport_specific = NBAExt()

        return CanonicalResult(
            sport="nba",
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
            sport="nba",
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
        adv = res["sport_specific"].get("advanced") if "sport_specific" in res else None
        oo = res["sport_specific"].get("on_off") if "sport_specific" in res else None
        sport_specific = NBAExt(advanced=adv, on_off=oo)

        return CanonicalResult(
            sport="nba",
            query_type="team_stats",
            entity=entity,
            season=season,
            core=res["core"],
            sport_specific=sport_specific,
            meta=meta,
        )

    def get_team_game_log(
        self, team_name: str, season: str, limit: int = 82, **kwargs: Any
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
            sport="nba",
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
        sport_specific = NBAExt()

        return CanonicalResult(
            sport="nba",
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
            name="NBA League",
            sport="nba",
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
        sport_specific = NBAExt()

        return CanonicalResult(
            sport="nba",
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
            sport="nba",
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
        sport_specific = NBAExt()

        return CanonicalResult(
            sport="nba",
            query_type="team_history",
            entity=entity,
            season=None,
            core=res["core"],
            sport_specific=sport_specific,
            meta=meta,
        )
