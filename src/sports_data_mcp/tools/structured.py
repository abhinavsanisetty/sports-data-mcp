"""
Structured MCP tool dispatcher (§5.4 Phase 4).

Wraps sport adapters with cache and name/stat resolvers.
"""
from __future__ import annotations

import logging
from typing import Any

import sports_data_mcp.cache
from sports_data_mcp.cache import Cache
from sports_data_mcp.names.resolver import NameResolver
from sports_data_mcp.stats.resolver import StatResolver

logger = logging.getLogger(__name__)


# Monkey-patch cache._is_meaningful to support checking serialized CanonicalResult dicts
_orig_is_meaningful = sports_data_mcp.cache._is_meaningful


def _patched_is_meaningful(query_type: str, result: Any) -> bool:
    if isinstance(result, dict) and "sport" in result and "query_type" in result:
        core = result.get("core", {})
        if query_type in ("player_game_log", "team_game_log"):
            games = core.get("games")
            return isinstance(games, list) and len(games) > 0
        if query_type == "league_leaders":
            leaders = core.get("leaders")
            return isinstance(leaders, list) and len(leaders) > 0
        if query_type == "team_history":
            return isinstance(core, dict) and len(core) > 0
        if query_type in ("player_stats", "team_stats"):
            return any(isinstance(v, (int, float)) for v in core.values())
    return _orig_is_meaningful(query_type, result)


sports_data_mcp.cache._is_meaningful = _patched_is_meaningful


class StructuredDispatcher:
    """
    Dispatches validated tool calls to the appropriate sport adapter.

    Handles caching and entity/stat resolution.
    """

    def __init__(
        self,
        adapter: Any,
        cache: Cache,
        name_resolver: NameResolver,
        stat_resolver: StatResolver,
    ) -> None:
        self.adapter = adapter
        self.cache = cache
        self.name_resolver = name_resolver
        self.stat_resolver = stat_resolver

    def call(self, tool: str, args: dict) -> dict:
        """
        Execute tool call.

        1. Checks SQLite cache for hit.
        2. On miss, resolves ambiguous player/team/stat names to canonical equivalents.
        3. Calls the adapter method dynamically.
        4. Serializes the CanonicalResult to dict with by_alias=True (so _meta is output).
        5. Attempts to write to cache, filtered by is_meaningful and below_threshold guards.
        """
        query_type = tool
        if query_type.startswith("get_"):
            query_type = query_type[4:]

        # 1. Checks cache
        cached = self.cache.get(tool, args)
        if cached is not None:
            logger.info("Cache hit for tool %r with args %s", tool, args)
            return cached

        # Resolve args before calling adapter method
        resolved_args = dict(args)
        sport = resolved_args.get("sport")

        if "player_name" in resolved_args:
            resolved = self.name_resolver.resolve(resolved_args["player_name"], sport)
            if resolved.confidence == "ambiguous":
                return {
                    "status": "error",
                    "error": (
                        f"Ambiguous player name {resolved_args['player_name']!r}. "
                        f"Candidates: {resolved.candidates}"
                    ),
                }
            resolved_args["player_name"] = resolved.canonical

        if "team_name" in resolved_args:
            resolved = self.name_resolver.resolve(resolved_args["team_name"], sport)
            if resolved.confidence == "ambiguous":
                return {
                    "status": "error",
                    "error": (
                        f"Ambiguous team name {resolved_args['team_name']!r}. "
                        f"Candidates: {resolved.candidates}"
                    ),
                }
            resolved_args["team_name"] = resolved.canonical

        if "stat" in resolved_args:
            resolved = self.stat_resolver.resolve(resolved_args["stat"], sport)
            if resolved.canonical is None:
                return {
                    "status": "error",
                    "error": f"Unknown stat {resolved_args['stat']!r} for sport {sport}.",
                }
            resolved_args["stat"] = resolved.canonical

        # 2. Call adapter method
        if not hasattr(self.adapter, tool):
            name = type(self.adapter).__name__
            return {
                "status": "error",
                "error": f"Adapter {name} does not implement method {tool!r}.",
            }

        method = getattr(self.adapter, tool)
        canonical_result = method(**resolved_args)

        # 3. Serializes CanonicalResult with by_alias=True so _meta is the cache write guard
        serialized = canonical_result.model_dump(mode="json", by_alias=True)
        serialized["status"] = "ok"

        # 4. Calls cache.set() with query_type
        self.cache.set(tool, args, serialized, query_type=query_type)

        return serialized
