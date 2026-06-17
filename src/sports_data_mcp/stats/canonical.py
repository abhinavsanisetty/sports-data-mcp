"""
Canonical stat enums per sport (§2.3, §5.4 Phase 0).

These enums define the single source of truth for stat naming across the project:
- Tool documentation and list_sports output reference these names
- Adapter alias dicts map source-native names to these values (Phase 3+)
- Gemini fallback in stats/resolver.py uses these as the resolution target

NBA and MLB are fully populated here (needed by Phase 1 eval generation).
NFL, NHL, Soccer, and NCAA enums are filled in alongside their adapters (Phase 5).
"""
from enum import StrEnum


class NBAStatEnum(StrEnum):
    """Canonical NBA stat names."""

    # Counting stats
    POINTS = "points"
    ASSISTS = "assists"
    REBOUNDS = "rebounds"
    OFFENSIVE_REBOUNDS = "offensive_rebounds"
    DEFENSIVE_REBOUNDS = "defensive_rebounds"
    STEALS = "steals"
    BLOCKS = "blocks"
    TURNOVERS = "turnovers"
    PERSONAL_FOULS = "personal_fouls"
    MINUTES = "minutes"
    GAMES_PLAYED = "games_played"
    GAMES_STARTED = "games_started"

    # Shooting
    FIELD_GOALS_MADE = "field_goals_made"
    FIELD_GOALS_ATTEMPTED = "field_goals_attempted"
    FIELD_GOAL_PCT = "field_goal_pct"
    THREE_POINTERS_MADE = "three_pointers_made"
    THREE_POINTERS_ATTEMPTED = "three_pointers_attempted"
    THREE_POINT_PCT = "three_point_pct"
    FREE_THROWS_MADE = "free_throws_made"
    FREE_THROWS_ATTEMPTED = "free_throws_attempted"
    FREE_THROW_PCT = "free_throw_pct"

    # Advanced
    TRUE_SHOOTING_PCT = "true_shooting_pct"
    PLAYER_EFFICIENCY_RATING = "player_efficiency_rating"
    WIN_SHARES = "win_shares"
    BOX_PLUS_MINUS = "box_plus_minus"
    VALUE_OVER_REPLACEMENT = "value_over_replacement"
    PLUS_MINUS = "plus_minus"
    USAGE_RATE = "usage_rate"
    OFFENSIVE_RATING = "offensive_rating"
    DEFENSIVE_RATING = "defensive_rating"


class MLBStatEnum(StrEnum):
    """Canonical MLB stat names (batting + pitching)."""

    # Batting — counting
    BATTING_AVG = "batting_avg"
    HOME_RUNS = "home_runs"
    RBI = "rbi"
    HITS = "hits"
    RUNS = "runs"
    DOUBLES = "doubles"
    TRIPLES = "triples"
    STOLEN_BASES = "stolen_bases"
    CAUGHT_STEALING = "caught_stealing"
    WALKS = "walks"
    STRIKEOUTS_BATTING = "strikeouts_batting"
    HIT_BY_PITCH = "hit_by_pitch"
    GAMES_PLAYED = "games_played"
    AT_BATS = "at_bats"
    PLATE_APPEARANCES = "plate_appearances"

    # Batting — rate & advanced
    ON_BASE_PCT = "on_base_pct"
    SLUGGING_PCT = "slugging_pct"
    OPS = "ops"
    OPS_PLUS = "ops_plus"
    BATTING_WAR = "batting_war"
    WOBA = "woba"
    WRAC = "wrac"

    # Pitching — counting
    ERA = "era"
    WINS = "wins"
    LOSSES = "losses"
    SAVES = "saves"
    HOLDS = "holds"
    STRIKEOUTS_PITCHING = "strikeouts_pitching"
    WALKS_ALLOWED = "walks_allowed"
    HITS_ALLOWED = "hits_allowed"
    HOME_RUNS_ALLOWED = "home_runs_allowed"
    INNINGS_PITCHED = "innings_pitched"
    COMPLETE_GAMES = "complete_games"
    SHUTOUTS = "shutouts"
    GAMES_PITCHED = "games_pitched"
    GAMES_STARTED = "games_started"

    # Pitching — rate & advanced
    WHIP = "whip"
    ERA_PLUS = "era_plus"
    FIP = "fip"
    XFIP = "xfip"
    K_PER_9 = "k_per_9"
    BB_PER_9 = "bb_per_9"
    H_PER_9 = "h_per_9"
    PITCHING_WAR = "pitching_war"


class NFLStatEnum(StrEnum):
    """Canonical NFL stat names."""

    GAMES_PLAYED = "games_played"

    # Passing
    PASSING_YARDS = "passing_yards"
    PASSING_TDS = "passing_tds"
    INTERCEPTIONS_THROWN = "interceptions_thrown"
    COMPLETIONS = "completions"
    PASS_ATTEMPTS = "pass_attempts"
    COMPLETION_PCT = "completion_pct"
    PASSER_RATING = "passer_rating"
    ANY_A = "any_a"  # adjusted net yards per pass attempt

    # Rushing
    RUSHING_YARDS = "rushing_yards"
    RUSHING_TDS = "rushing_tds"
    CARRIES = "carries"
    YARDS_PER_CARRY = "yards_per_carry"

    # Receiving
    RECEIVING_YARDS = "receiving_yards"
    RECEIVING_TDS = "receiving_tds"
    RECEPTIONS = "receptions"
    TARGETS = "targets"
    YARDS_PER_RECEPTION = "yards_per_reception"

    # Defense
    SACKS = "sacks"
    TACKLES = "tackles"
    TACKLES_FOR_LOSS = "tackles_for_loss"
    INTERCEPTIONS = "interceptions"
    FORCED_FUMBLES = "forced_fumbles"
    FUMBLE_RECOVERIES = "fumble_recoveries"
    PASSES_DEFENDED = "passes_defended"

    # General
    TOUCHDOWNS = "touchdowns"
    FUMBLES_LOST = "fumbles_lost"


class NHLStatEnum(StrEnum):
    """Canonical NHL stat names (skater + goalie)."""

    GAMES_PLAYED = "games_played"

    # Skater — counting
    GOALS = "goals"
    ASSISTS = "assists"
    POINTS = "points"
    PLUS_MINUS = "plus_minus"
    PENALTY_MINUTES = "penalty_minutes"
    POWER_PLAY_GOALS = "power_play_goals"
    POWER_PLAY_ASSISTS = "power_play_assists"
    SHORTHANDED_GOALS = "shorthanded_goals"
    GAME_WINNING_GOALS = "game_winning_goals"
    SHOTS = "shots"
    HITS = "hits"
    BLOCKED_SHOTS = "blocked_shots"

    # Skater — rate
    SHOOTING_PCT = "shooting_pct"
    TIME_ON_ICE = "time_on_ice"
    POINTS_PER_GAME = "points_per_game"

    # Goalie
    WINS = "wins"
    LOSSES = "losses"
    OVERTIME_LOSSES = "overtime_losses"
    SAVES = "saves"
    GOALS_AGAINST_AVG = "goals_against_avg"
    SAVE_PCT = "save_pct"
    SHUTOUTS = "shutouts"
    GOALS_AGAINST = "goals_against"


class SoccerStatEnum(StrEnum):
    """Canonical soccer stat names (outfield + goalkeeper)."""

    APPEARANCES = "appearances"
    MINUTES_PLAYED = "minutes_played"
    YELLOW_CARDS = "yellow_cards"
    RED_CARDS = "red_cards"

    # Outfield — attacking
    GOALS = "goals"
    ASSISTS = "assists"
    SHOTS = "shots"
    SHOTS_ON_TARGET = "shots_on_target"
    KEY_PASSES = "key_passes"
    DRIBBLES_COMPLETED = "dribbles_completed"
    EXPECTED_GOALS = "expected_goals"
    EXPECTED_ASSISTS = "expected_assists"

    # Outfield — defensive
    TACKLES = "tackles"
    INTERCEPTIONS = "interceptions"
    CLEARANCES = "clearances"
    BLOCKS = "blocks"

    # Goalkeeper
    CLEAN_SHEETS = "clean_sheets"
    SAVES = "saves"
    SAVE_PCT = "save_pct"
    GOALS_AGAINST = "goals_against"
    GOALS_AGAINST_AVG = "goals_against_avg"


class NCAAStatEnum(StrEnum):
    """Canonical NCAA stat names (basketball + football, shared where possible)."""

    GAMES_PLAYED = "games_played"

    # Basketball
    POINTS = "points"
    ASSISTS = "assists"
    REBOUNDS = "rebounds"
    STEALS = "steals"
    BLOCKS = "blocks"
    FIELD_GOAL_PCT = "field_goal_pct"
    THREE_POINT_PCT = "three_point_pct"
    FREE_THROW_PCT = "free_throw_pct"
    TURNOVERS = "turnovers"
    MINUTES = "minutes"

    # Football — offense
    PASSING_YARDS = "passing_yards"
    PASSING_TDS = "passing_tds"
    RUSHING_YARDS = "rushing_yards"
    RUSHING_TDS = "rushing_tds"
    RECEIVING_YARDS = "receiving_yards"
    RECEIVING_TDS = "receiving_tds"
    RECEPTIONS = "receptions"

    # Football — defense
    SACKS = "sacks"
    INTERCEPTIONS = "interceptions"
    TACKLES = "tackles"


# ---------------------------------------------------------------------------
# Convenience lookup used by stats/resolver.py (Phase 3)
# ---------------------------------------------------------------------------

SPORT_STAT_ENUM: dict[str, type[StrEnum]] = {
    "nba": NBAStatEnum,
    "mlb": MLBStatEnum,
    "nfl": NFLStatEnum,
    "nhl": NHLStatEnum,
    "soccer": SoccerStatEnum,
    "ncaa": NCAAStatEnum,
}
