"""
Tool contract: Pydantic models for every structured tool's input shape (§5.4 Phase 0).

This module is the shared foundation read by:
  - eval generation (Phase 1): scripts/generate_evals.py imports these to produce valid plans
  - tool dispatch (Phase 2+): server.py validates incoming args against these models
  - NL routing (Phase 6): ExecutionPlan is validated before any tool is called

No business logic, no I/O, no imports from within this package.
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared literals (duplicated here to keep this module import-free)
# ---------------------------------------------------------------------------

SportLiteral = Literal["nba", "nfl", "mlb", "nhl", "soccer", "ncaa"]

ToolNameLiteral = Literal[
    "get_player_stats",
    "get_player_game_log",
    "get_team_stats",
    "get_team_game_log",
    "get_league_leaders",
    "get_team_history",
    "list_sports",
]


# ---------------------------------------------------------------------------
# Structured tool argument models
# ---------------------------------------------------------------------------


class GetPlayerStatsArgs(BaseModel):
    sport: SportLiteral
    player_name: str
    season: str | None = None  # e.g. "2016" or "2016-17"; None = career totals/averages


class GetPlayerGameLogArgs(BaseModel):
    sport: SportLiteral
    player_name: str
    season: str  # required; game logs are always season-scoped
    limit: Annotated[int, Field(ge=1, le=500)] = 82  # 82 covers a full NBA regular season


class GetTeamStatsArgs(BaseModel):
    sport: SportLiteral
    team_name: str
    season: str | None = None  # None = most recent completed season


class GetTeamGameLogArgs(BaseModel):
    sport: SportLiteral
    team_name: str
    season: str  # required
    limit: Annotated[int, Field(ge=1, le=500)] = 82


class GetLeagueLeadersArgs(BaseModel):
    sport: SportLiteral
    stat: str  # canonical stat name; see list_sports for valid values per sport
    season: str | None = None  # None = career leaders
    limit: Annotated[int, Field(ge=1, le=100)] = 10


class GetTeamHistoryArgs(BaseModel):
    sport: SportLiteral
    team_name: str  # championships, season records, relocations, name changes


class ListSportsArgs(BaseModel):
    pass  # no args; returns supported sports, canonical stat names, season format info


# ---------------------------------------------------------------------------
# NL execution plan — produced by Haiku in tools/nl_query.py (§4.3.d)
#
# The tool field is a strict Literal enum; any value outside this set is a
# Pydantic validation error, which the NL tool converts to a clean error
# response without attempting execution. This prevents SSRF and prompt injection
# from expanding the server's action surface.
# ---------------------------------------------------------------------------


class ExecutionPlan(BaseModel):
    """Validated routing plan returned by Claude Haiku for nl_sports_query."""

    tool: ToolNameLiteral
    args: dict[str, str | int | float | bool | None]


# ---------------------------------------------------------------------------
# Dispatch table: tool name → args model (used by server.py in Phase 2+)
# ---------------------------------------------------------------------------

TOOL_ARGS_MAP: dict[str, type[BaseModel]] = {
    "get_player_stats": GetPlayerStatsArgs,
    "get_player_game_log": GetPlayerGameLogArgs,
    "get_team_stats": GetTeamStatsArgs,
    "get_team_game_log": GetTeamGameLogArgs,
    "get_league_leaders": GetLeagueLeadersArgs,
    "get_team_history": GetTeamHistoryArgs,
    "list_sports": ListSportsArgs,
}
