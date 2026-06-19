"""
MCP server entry point (§5.4 Phase 2).

Transport: stdio only (HTTP in Phase 7).
Registers all 7 tools from ToolNameLiteral.
Validates incoming args against TOOL_ARGS_MAP.
Dispatches to adapter registry (empty → not_implemented until Phase 4).
list_sports returns supported sports and canonical stat names from SPORT_STAT_ENUM.

Stdout is redirected to stderr in stdio mode to protect the MCP protocol (§4.5.a).
"""
from __future__ import annotations

import json
import logging
import sys
from typing import Any

from pydantic import ValidationError

from sports_data_mcp.stats.canonical import SPORT_STAT_ENUM
from sports_data_mcp.tools.contract import TOOL_ARGS_MAP, ToolNameLiteral

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Adapter registry — populated per sport in Phase 4+
# ---------------------------------------------------------------------------

_ADAPTER_REGISTRY: dict[str, Any] = {}  # sport → BaseSportAdapter instance


def register_adapter(sport: str, adapter: Any) -> None:
    _ADAPTER_REGISTRY[sport] = adapter


_config: Any = None
_cache: Any = None
_name_resolver: Any = None
_stat_resolver: Any = None
_bootstrapped = False


def _bootstrap() -> None:
    global _config, _cache, _name_resolver, _stat_resolver, _bootstrapped
    if _bootstrapped:
        return
    from sports_data_mcp.cache import Cache
    from sports_data_mcp.config import load_config
    from sports_data_mcp.names.resolver import NameResolver
    from sports_data_mcp.stats.resolver import StatResolver

    _config = load_config()
    _cache = Cache(
        db_path=_config.cache_path,
        cache_version=_config.cache_version,
        wal_mode=(_config.transport == "http"),
    )
    _name_resolver = NameResolver(_cache, api_key=_config.gemini_api_key, model=_config.model)
    _stat_resolver = StatResolver(api_key=_config.gemini_api_key, model=_config.model)

    from sports_data_mcp.sports.mlb import MLBAdapter
    from sports_data_mcp.sports.nba import NBAAdapter
    register_adapter("nba", NBAAdapter())
    register_adapter("mlb", MLBAdapter())

    _bootstrapped = True


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


def _handle_list_sports(_args: dict) -> dict:
    return {
        "status": "ok",
        "sports": {
            sport: [stat.value for stat in enum_cls]
            for sport, enum_cls in SPORT_STAT_ENUM.items()
        },
    }


def _handle_not_implemented(tool: str, _args: dict) -> dict:
    return {"status": "not_implemented", "tool": tool}


def _dispatch(tool: str, args: dict) -> dict:
    """Route a validated tool call to the correct handler."""
    if tool == "list_sports":
        return _handle_list_sports(args)

    # All other tools need an adapter for the requested sport
    sport = args.get("sport")
    if sport and sport in _ADAPTER_REGISTRY:
        adapter = _ADAPTER_REGISTRY[sport]
        from sports_data_mcp.tools.structured import StructuredDispatcher
        dispatcher = StructuredDispatcher(adapter, _cache, _name_resolver, _stat_resolver)
        return dispatcher.call(tool, args)

    return _handle_not_implemented(tool, args)



# ---------------------------------------------------------------------------
# SportsServer — the public interface used by eval harness and MCP loop
# ---------------------------------------------------------------------------


class SportsServer:
    """
    Callable MCP server.

    call_tool(tool_name, args) is the primary entry point used by the eval
    harness and will be called by the MCP protocol loop.
    """

    def call_tool(self, tool_name: str, args: dict) -> dict:
        """Validate args and dispatch; return a result dict."""
        _bootstrap()
        if tool_name not in TOOL_ARGS_MAP:
            return {
                "status": "error",
                "error": f"Unknown tool {tool_name!r}. "
                f"Valid tools: {list(TOOL_ARGS_MAP.keys())}",
            }

        args_model_cls = TOOL_ARGS_MAP[tool_name]
        try:
            validated = args_model_cls.model_validate(args)
        except ValidationError as exc:
            return {
                "status": "error",
                "error": f"Invalid args for {tool_name!r}: {exc.errors(include_url=False)}",
            }

        return _dispatch(tool_name, validated.model_dump())

    # ------------------------------------------------------------------
    # stdio MCP loop (stubbed; full protocol in Phase 7)
    # ------------------------------------------------------------------

    def run_stdio(self) -> None:
        """
        Run a minimal stdio MCP loop (JSON-RPC lines on stdin/stdout).

        Stdout is redirected to stderr before this runs so sports library
        print() calls don't corrupt the MCP protocol (§4.5.a).
        """
        sys.stdout = sys.stderr  # type: ignore[assignment]
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
                tool = request.get("tool", "")
                args = request.get("args", {})
                result = self.call_tool(tool, args)
                sys.stderr.write(json.dumps(result) + "\n")
                sys.stderr.flush()
            except Exception as exc:
                sys.stderr.write(json.dumps({"status": "error", "error": str(exc)}) + "\n")
                sys.stderr.flush()


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    server = SportsServer()
    server.run_stdio()


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# Re-export ToolNameLiteral so callers can import from here
# ---------------------------------------------------------------------------

__all__ = ["SportsServer", "register_adapter", "ToolNameLiteral"]
