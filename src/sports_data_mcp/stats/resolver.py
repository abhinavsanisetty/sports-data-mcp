"""
Stat resolver: enum → alias dict → Gemini fallback chain (§2.3, §4.3.b).

Public API: resolve(raw, sport) -> ResolvedStat
Tier 1 (enum): exact match against canonical StrEnum values for the sport.
Tier 2 (alias): STAT_ALIASES dict maps common shorthands to canonical names.
Tier 3 (gemini): Gemini is prompted with the sport's canonical stat list.
On Gemini failure or unknown: tier="unknown", canonical=None; never raises.
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.request
from typing import Literal

from pydantic import BaseModel

from sports_data_mcp.stats.canonical import SPORT_STAT_ENUM
from sports_data_mcp.types import SportLiteral

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# API key redaction (§4.3.b)
# ---------------------------------------------------------------------------

_KEY_PATTERN = re.compile(r"AIza[0-9A-Za-z\-_]{10,}")


class _RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Render the full message (including args such as Exception objects whose
        # str() can embed the API-keyed URL) and redact the result, then clear
        # args so downstream formatting is a no-op. Redacting only string args
        # missed non-string args like exceptions, leaking the key (§4.3.b).
        try:
            rendered = record.getMessage()
        except Exception:
            rendered = str(record.msg)
        record.msg = _KEY_PATTERN.sub("***", rendered)
        record.args = None
        return True


logger.addFilter(_RedactFilter())

# ---------------------------------------------------------------------------
# Alias dicts: sport → {alias_lower: canonical_value}
# ~3 aliases per sport for NBA and MLB (others added alongside adapters)
# ---------------------------------------------------------------------------

STAT_ALIASES: dict[str, dict[str, str]] = {
    "nba": {
        "pts": "points",
        "reb": "rebounds",
        "ast": "assists",
        "blk": "blocks",
        "stl": "steals",
        "to": "turnovers",
        "fgp": "field_goal_pct",
        "ftm": "free_throws_made",
        "3pm": "three_pointers_made",
    },
    "mlb": {
        "avg": "batting_avg",
        "hr": "home_runs",
        "era": "era",
        "whip": "whip",
        "sb": "stolen_bases",
        "so": "strikeouts_pitching",
        "bb": "walks",
        "ops": "ops",
    },
    "nfl": {
        "td": "touchdowns",
        "int": "interceptions",
        "yds": "rushing_yards",
    },
    "nhl": {
        "g": "goals",
        "a": "assists",
        "gaa": "goals_against_avg",
        "sv": "saves",
        "svp": "save_pct",
    },
    "soccer": {
        "ga": "goals_against",
        "cs": "clean_sheets",
        "xg": "expected_goals",
    },
    "ncaa": {
        "pts": "points",
        "reb": "rebounds",
        "ast": "assists",
    },
}

# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


class ResolvedStat(BaseModel):
    canonical: str | None
    sport: SportLiteral
    tier: Literal["enum", "alias", "gemini", "unknown"]
    raw: str


# ---------------------------------------------------------------------------
# Gemini prompt
# ---------------------------------------------------------------------------

_GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
_DEFAULT_MODEL = "gemini-2.0-flash"

_STAT_PROMPT_TEMPLATE = (
    "You are a sports stat resolver. Given a stat name, return the matching canonical name.\n\n"
    "Sport: {sport}\n"
    "Canonical stats for this sport:\n{canonical_list}\n\n"
    "Input: <stat_name>{raw}</stat_name>\n\n"
    "Respond with JSON only (no markdown, no extra text):\n"
    '{{\n'
    '  "canonical": "<exact canonical name from the list above, or null if no match>"\n'
    "}}\n\n"
    "Return null if the stat has no reasonable match in the list."
)


# ---------------------------------------------------------------------------
# Resolver class
# ---------------------------------------------------------------------------


class StatResolver:
    """Resolves stat names to canonical form via enum → alias → Gemini chain."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = _DEFAULT_MODEL,
    ) -> None:
        self._api_key = api_key if api_key is not None else os.environ.get("GEMINI_API_KEY")
        self._model = model

    def resolve(self, raw: str, sport: str) -> ResolvedStat:
        """Resolve *raw* stat name for *sport*. Never raises."""
        normalized = raw.lower().strip()
        enum_cls = SPORT_STAT_ENUM.get(sport)

        # Tier 1: enum match (check if raw matches any canonical value exactly)
        if enum_cls is not None:
            canonical_values = {e.value for e in enum_cls}
            if normalized in canonical_values:
                return ResolvedStat(
                    canonical=normalized,
                    sport=sport,  # type: ignore[arg-type]
                    tier="enum",
                    raw=raw,
                )

        # Tier 2: alias dict
        sport_aliases = STAT_ALIASES.get(sport, {})
        if normalized in sport_aliases:
            return ResolvedStat(
                canonical=sport_aliases[normalized],
                sport=sport,  # type: ignore[arg-type]
                tier="alias",
                raw=raw,
            )

        # Tier 3: Gemini fallback (only if API key is available)
        if self._api_key and enum_cls is not None:
            return self._call_gemini(raw, sport, enum_cls)

        return ResolvedStat(
            canonical=None,
            sport=sport,  # type: ignore[arg-type]
            tier="unknown",
            raw=raw,
        )

    def _call_gemini(self, raw: str, sport: str, enum_cls) -> ResolvedStat:
        """Call Gemini to match stat against the canonical list. On failure, return unknown."""
        canonical_list = "\n".join(f"- {e.value}" for e in enum_cls)
        prompt = _STAT_PROMPT_TEMPLATE.format(
            sport=sport, canonical_list=canonical_list, raw=raw
        )
        payload = json.dumps(
            {"contents": [{"parts": [{"text": prompt}], "role": "user"}]}
        ).encode()
        url = f"{_GEMINI_API_BASE}/{self._model}:generateContent?key={self._api_key}"
        req = urllib.request.Request(
            url,
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
                response_data = json.loads(resp.read())
            text = response_data["candidates"][0]["content"]["parts"][0]["text"].strip()
            text = re.sub(r"^```[a-z]*\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            data = json.loads(text)
            canonical = data.get("canonical")
            if canonical is None or canonical == "null":
                return ResolvedStat(
                    canonical=None,
                    sport=sport,  # type: ignore[arg-type]
                    tier="unknown",
                    raw=raw,
                )
            # Validate returned canonical is actually in the enum
            canonical_values = {e.value for e in enum_cls}
            if canonical not in canonical_values:
                logger.warning(
                    "Gemini returned stat %r not in canonical list for %s", canonical, sport
                )
                return ResolvedStat(
                    canonical=None,
                    sport=sport,  # type: ignore[arg-type]
                    tier="unknown",
                    raw=raw,
                )
            return ResolvedStat(
                canonical=canonical,
                sport=sport,  # type: ignore[arg-type]
                tier="gemini",
                raw=raw,
            )
        except Exception as exc:
            logger.warning("Gemini stat resolution failed for %r/%s: %s", raw, sport, exc)
            return ResolvedStat(
                canonical=None,
                sport=sport,  # type: ignore[arg-type]
                tier="unknown",
                raw=raw,
            )
