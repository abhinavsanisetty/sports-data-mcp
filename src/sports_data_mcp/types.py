"""
Core types shared across the entire project.

CanonicalResult is the output schema every adapter produces.
ResultMeta is the observability envelope attached to every response (§4.6.a).
BaseSportExt and its subclasses hold typed per-sport data (§3.34).

No imports from within this package — safe to import from anywhere.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Shared literals
# ---------------------------------------------------------------------------

SportLiteral = Literal["nba", "nfl", "mlb", "nhl", "soccer", "ncaa"]
QueryTypeLiteral = Literal[
    "player_stats",
    "player_game_log",
    "team_stats",
    "team_game_log",
    "league_leaders",
    "team_history",
]


# ---------------------------------------------------------------------------
# Entity
# ---------------------------------------------------------------------------


class Entity(BaseModel):
    """Canonical identifier for a player or team."""

    name: str
    sport: SportLiteral
    entity_type: Literal["player", "team"]
    canonical_id: str | None = None  # source-specific ID when known (e.g. nba_api player_id)


# ---------------------------------------------------------------------------
# ResultMeta — observability envelope (§4.6.a)
# ---------------------------------------------------------------------------


class ResultMeta(BaseModel):
    source: str  # which source ultimately served this result
    attempted_sources: list[str]  # ordered list of sources tried, including failures
    cache_status: Literal["hit", "miss", "bypassed"]
    fetched_at: int  # unix timestamp
    latency_ms: int  # total wall-clock time across the full fallback chain
    below_threshold: bool = False  # set when min_records (§4.1) was not satisfied by any source
    truncated: bool = False  # set when result was capped by MAX_RECORDS (§4.5.b)
    total_available: int | None = None  # original record count before truncation


# ---------------------------------------------------------------------------
# Per-sport extension models (§3.34)
#
# These hold sport-specific data that doesn't fit in the canonical core dict.
# Adapters instantiate the correct subclass; callers may inspect sport_specific
# after checking CanonicalResult.sport.
# ---------------------------------------------------------------------------


class BaseSportExt(BaseModel):
    """Base class for per-sport extension data. Each sport subclasses this."""


class NBAExt(BaseSportExt):
    advanced: dict | None = None  # true_shooting_pct, per_possession stats, etc.
    on_off: dict | None = None  # on/off court net rating splits


class NFLExt(BaseSportExt):
    position_group: str | None = None  # QB | RB | WR | TE | DEF
    passer_rating: float | None = None
    air_yards: dict | None = None  # intended / completed air yards


class MLBExt(BaseSportExt):
    splits: dict | None = None  # left_vs_right, home_vs_away, etc.
    pitch_mix: dict | None = None  # pitcher-specific pitch-type breakdown


class NHLExt(BaseSportExt):
    position: str | None = None  # F | D | G
    power_play: dict | None = None  # PP goals, assists, time
    goalie_stats: dict | None = None  # save breakdown by shot type


class SoccerExt(BaseSportExt):
    competition: str | None = None  # e.g. "Premier League", "Champions League"
    xg: float | None = None  # expected goals
    xga: float | None = None  # expected goals against (for keepers)


class NCAAExt(BaseSportExt):
    division: str | None = None  # FBS | FCS | D1 | D2 | D3
    conference: str | None = None


# Convenience lookup: sport string → extension class
SPORT_EXT_MAP: dict[str, type[BaseSportExt]] = {
    "nba": NBAExt,
    "nfl": NFLExt,
    "mlb": MLBExt,
    "nhl": NHLExt,
    "soccer": SoccerExt,
    "ncaa": NCAAExt,
}


# ---------------------------------------------------------------------------
# CanonicalResult — the unified output schema every adapter returns (§3.34)
# ---------------------------------------------------------------------------


class CanonicalResult(BaseModel):
    sport: SportLiteral
    query_type: QueryTypeLiteral
    entity: Entity
    season: str | None = None  # None for career stats or all-time team history
    core: dict  # sport-agnostic stats: games_played, primary scoring stat, etc.
    sport_specific: BaseSportExt  # typed per-sport extension; instantiate the right subclass
    meta: ResultMeta = Field(serialization_alias="_meta")
