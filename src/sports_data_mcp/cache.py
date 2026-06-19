"""
SQLite cache with versioned keys and insert-time write guard (§2.4, §4.4.a, §4.7).

Key schema: (tool_name, sha256(sorted_json(args)), cache_version) → JSON blob.
WAL mode is enabled only when transport=http (§4.4.a).

Write rule: only write if is_meaningful(result) AND not result._meta.below_threshold.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_VERSION = "v1"
_DEFAULT_CACHE_PATH = Path.home() / ".sports-data-mcp" / "cache.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache (
    tool            TEXT NOT NULL,
    args_hash       TEXT NOT NULL,
    cache_version   TEXT NOT NULL,
    result_json     TEXT NOT NULL,
    stored_at       INTEGER NOT NULL,
    PRIMARY KEY (tool, args_hash, cache_version)
);
"""


# ---------------------------------------------------------------------------
# Per-query-type meaningful predicates (§4.7)
# ---------------------------------------------------------------------------

def _is_meaningful(query_type: str, result: Any) -> bool:
    """Return True if result contains enough data to be worth caching.

    Accepts either a raw adapter result (dict/list) or a serialized
    ``CanonicalResult`` wrapper (``{"sport", "query_type", "core", ...}``). When
    handed the wrapper, the meaningfulness check is applied to its ``core``
    payload, since that holds the actual stats/records (§4.7). This keeps the
    predicate in cache.py rather than monkey-patching it from the dispatcher.
    """
    if result is None:
        return False
    # Serialized CanonicalResult wrapper → inspect its core payload.
    if (
        isinstance(result, dict)
        and "core" in result
        and "sport" in result
        and "query_type" in result
    ):
        core = result.get("core")
        if query_type in ("player_game_log", "team_game_log"):
            games = core.get("games") if isinstance(core, dict) else None
            return isinstance(games, list) and len(games) > 0
        if query_type == "league_leaders":
            leaders = core.get("leaders") if isinstance(core, dict) else None
            return isinstance(leaders, list) and len(leaders) > 0
        if query_type == "team_history":
            return isinstance(core, dict) and len(core) > 0
        if query_type in ("player_stats", "team_stats"):
            return isinstance(core, dict) and any(
                isinstance(v, (int, float)) for v in core.values()
            )
        return isinstance(core, (dict, list)) and len(core) > 0
    if query_type in ("player_stats", "team_stats"):
        if isinstance(result, dict):
            return any(isinstance(v, (int, float)) for v in result.values())
        return False
    if query_type in ("player_game_log", "team_game_log", "league_leaders"):
        return isinstance(result, list) and len(result) > 0
    if query_type == "team_history":
        return isinstance(result, dict) and len(result) > 0
    # Unknown query types: require non-empty
    if isinstance(result, dict):
        return len(result) > 0
    if isinstance(result, list):
        return len(result) > 0
    return result is not None


def _args_hash(args: dict) -> str:
    canonical = json.dumps(args, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Cache class
# ---------------------------------------------------------------------------

class Cache:
    """Thread-safe SQLite cache for tool results."""

    def __init__(
        self,
        db_path: Path = _DEFAULT_CACHE_PATH,
        cache_version: str = _DEFAULT_VERSION,
        *,
        wal_mode: bool = False,
    ) -> None:
        self._db_path = Path(db_path)
        self._cache_version = cache_version
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.isolation_level = None  # autocommit for explicit transactions
        if wal_mode:
            self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute(_SCHEMA)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, tool: str, args: dict) -> Any | None:
        """Return cached result or None on miss."""
        h = _args_hash(args)
        row = self._conn.execute(
            "SELECT result_json FROM cache WHERE tool=? AND args_hash=? AND cache_version=?",
            (tool, h, self._cache_version),
        ).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            logger.warning("Cache entry for %s/%s is corrupt; evicting.", tool, h[:8])
            self._conn.execute(
                "DELETE FROM cache WHERE tool=? AND args_hash=? AND cache_version=?",
                (tool, h, self._cache_version),
            )
            return None

    def set(self, tool: str, args: dict, result: Any, *, query_type: str = "") -> bool:
        """
        Write result to cache.

        Returns True if the entry was written, False if the write guard rejected it.
        Write rule: is_meaningful(result) AND not result._meta.below_threshold (§4.7).
        """
        # Check below_threshold via _meta if present
        below_threshold = False
        if isinstance(result, dict):
            meta = result.get("_meta") or result.get("meta") or {}
            if isinstance(meta, dict):
                below_threshold = bool(meta.get("below_threshold", False))

        if below_threshold:
            logger.debug("Cache write rejected for %s: below_threshold=True", tool)
            return False

        if query_type and not _is_meaningful(query_type, result):
            logger.warning(
                "Cache write rejected for %s/%s: result not meaningful.", tool, query_type
            )
            return False

        h = _args_hash(args)
        blob = json.dumps(result, separators=(",", ":"))
        self._conn.execute(
            """
            INSERT OR REPLACE INTO cache (tool, args_hash, cache_version, result_json, stored_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (tool, h, self._cache_version, blob, int(time.time())),
        )
        return True

    def clear(self, sport: str | None = None) -> int:
        """
        Delete cache entries.

        If sport is provided, only entries whose tool name contains the sport string
        are deleted (e.g. sport='nba' removes entries for tools tagged with 'nba').
        Returns the number of rows deleted.
        """
        if sport is None:
            cur = self._conn.execute("DELETE FROM cache")
        else:
            cur = self._conn.execute(
                "DELETE FROM cache WHERE tool LIKE ?",
                (f"%{sport}%",),
            )
        count = cur.rowcount
        logger.info("Cache cleared: %d entries removed (sport=%r).", count, sport)
        return count

    def close(self) -> None:
        self._conn.close()
