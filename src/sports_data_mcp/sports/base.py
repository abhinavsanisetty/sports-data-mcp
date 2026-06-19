"""
Abstract base class for sport adapters (§4.1).

Each sport subclasses BaseSportAdapter and provides:
  - sources: list[str] — ordered source identifiers to try
  - _fetch_from(source, query_type, **kwargs) — fetch from one source
  - min_records(query_type) [optional override] — minimum records for "success"
  - is_meaningful(query_type, result) [optional override] — cache write guard

_try_sources() implements the fallback chain:
  1. Iterates sources in order.
  2. If a source raises, logs and continues.
  3. If a source returns fewer than min_records, treats it as a failure and falls through.
  4. The last source's result is returned even if below threshold; result is tagged
     below_threshold=True in _meta (§4.1 operating specifics).
  5. Raises SourceExhaustedError if ALL sources fail (exception, not thin data).
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class SourceExhaustedError(Exception):
    """All sources in the fallback chain raised; no result could be obtained."""


# ---------------------------------------------------------------------------
# Default min_records thresholds (§4.1)
# ---------------------------------------------------------------------------

_DEFAULT_MIN_RECORDS: dict[str, int] = {
    "player_stats": 1,
    "team_stats": 1,
    "player_game_log": 10,
    "team_game_log": 10,
    "league_leaders": 5,
    "team_history": 1,
}


def _record_count(result: Any) -> int:
    """Heuristic: count how many records are in a result."""
    if isinstance(result, list):
        return len(result)
    if isinstance(result, dict):
        # A dict of stats (player_stats / team_stats) counts as 1 record if non-empty
        return 1 if result else 0
    return 0


class BaseSportAdapter(ABC):
    """Abstract adapter — subclass one per sport."""

    #: Ordered list of source identifiers to try.
    sources: list[str] = []

    # ------------------------------------------------------------------
    # Hooks — override per sport as needed
    # ------------------------------------------------------------------

    def min_records(self, query_type: str) -> int:
        """Minimum acceptable record count for a query type to count as success."""
        return _DEFAULT_MIN_RECORDS.get(query_type, 1)

    def is_meaningful(self, query_type: str, result: Any) -> bool:
        """Return True if result is worth caching (§4.7). Override per sport."""
        if result is None:
            return False
        if isinstance(result, dict):
            return len(result) > 0
        if isinstance(result, list):
            return len(result) > 0
        return True

    # ------------------------------------------------------------------
    # Abstract — implement per sport
    # ------------------------------------------------------------------

    @abstractmethod
    def _fetch_from(self, source: str, query_type: str, **kwargs: Any) -> Any:
        """Fetch data from `source` for `query_type`. Raise on failure."""

    # ------------------------------------------------------------------
    # Fallback chain
    # ------------------------------------------------------------------

    def _try_sources(self, query_type: str, **kwargs: Any) -> dict:
        """
        Try each source in order; return first result that meets min_records.

        Returns a dict with:
          "result": the data
          "source": which source served it
          "attempted": list of all tried sources
          "below_threshold": True if no source met min_records (last result returned)
        """
        if not self.sources:
            raise SourceExhaustedError(f"{type(self).__name__} has no configured sources.")

        min_n = self.min_records(query_type)
        attempted: list[str] = []
        last_result: Any = None
        last_source: str | None = None
        got_any_data: bool = False

        for source in self.sources:
            attempted.append(source)
            try:
                result = self._fetch_from(source, query_type, **kwargs)
            except Exception as exc:
                logger.warning("Source %r failed for %s: %s", source, query_type, exc)
                continue

            count = _record_count(result)
            if count >= min_n:
                logger.debug(
                    "Source %r returned %d records (min=%d) — success.", source, count, min_n
                )
                return {
                    "result": result,
                    "source": source,
                    "attempted": attempted,
                    "below_threshold": False,
                }

            # Below threshold — try next. Only track results that actually carry data
            # (a source returning None/empty is treated like a failure for fallthrough).
            logger.debug(
                "Source %r returned %d records (min=%d) — below threshold, trying next.",
                source,
                count,
                min_n,
            )
            if count > 0:
                last_result = result
                last_source = source
                got_any_data = True

        # All sources exhausted. If no source ever produced usable data (every source
        # either raised or returned nothing), there is nothing to return — raise so the
        # caller surfaces an error rather than caching/returning an empty best-effort.
        if not got_any_data:
            raise SourceExhaustedError(
                f"All sources {self.sources!r} failed to return data for {query_type}."
            )

        # Some sources returned thin data — return last result with below_threshold flag
        logger.warning(
            "All sources returned fewer than %d records for %s; returning best effort.",
            min_n,
            query_type,
        )
        return {
            "result": last_result,
            "source": last_source,
            "attempted": attempted,
            "below_threshold": True,
        }
