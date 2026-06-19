"""Tests for BaseSportAdapter: fallback chain, below_threshold tagging, SourceExhaustedError."""
from __future__ import annotations

import sys

sys.path.insert(0, "src")

import pytest

from sports_data_mcp.sports.base import BaseSportAdapter, SourceExhaustedError

# ---------------------------------------------------------------------------
# Stub adapters
# ---------------------------------------------------------------------------


class StubAdapter(BaseSportAdapter):
    """Controllable stub: sources list + per-source behavior map."""

    def __init__(self, source_responses: dict[str, object]) -> None:
        self.sources = list(source_responses.keys())
        self._responses = source_responses

    def _fetch_from(self, source: str, query_type: str, **kwargs) -> object:
        resp = self._responses[source]
        if isinstance(resp, Exception):
            raise resp
        return resp


# ---------------------------------------------------------------------------
# Fallback chain — success on first source
# ---------------------------------------------------------------------------


def test_first_source_success():
    adapter = StubAdapter(
        {
            "primary": [{"game": 1, "pts": 20}] * 10,
            "fallback": [{"game": 1, "pts": 15}] * 10,
        }
    )
    out = adapter._try_sources("player_game_log")
    assert out["source"] == "primary"
    assert out["below_threshold"] is False
    assert out["attempted"] == ["primary"]


def test_fallthrough_to_second_source_on_error():
    adapter = StubAdapter(
        {
            "primary": ValueError("source down"),
            "fallback": [{"game": i} for i in range(10)],
        }
    )
    out = adapter._try_sources("player_game_log")
    assert out["source"] == "fallback"
    assert out["below_threshold"] is False
    assert "primary" in out["attempted"]
    assert "fallback" in out["attempted"]


def test_fallthrough_to_second_source_on_thin_data():
    # First source returns too few records (< min=10 for player_game_log)
    adapter = StubAdapter(
        {
            "primary": [{"g": 1}],  # only 1 record
            "fallback": [{"g": i} for i in range(10)],  # 10 records
        }
    )
    out = adapter._try_sources("player_game_log")
    assert out["source"] == "fallback"
    assert out["below_threshold"] is False


def test_below_threshold_flag_when_all_sources_thin():
    adapter = StubAdapter(
        {
            "primary": [{"g": 1}],
            "fallback": [{"g": 2}],
        }
    )
    out = adapter._try_sources("player_game_log")
    assert out["below_threshold"] is True
    assert out["source"] == "fallback"


def test_all_sources_raise_raises_exhausted():
    adapter = StubAdapter(
        {
            "src1": RuntimeError("timeout"),
            "src2": ConnectionError("refused"),
        }
    )
    with pytest.raises(SourceExhaustedError):
        adapter._try_sources("player_stats")


def test_no_sources_raises_exhausted():
    class Empty(BaseSportAdapter):
        sources = []

        def _fetch_from(self, source, query_type, **kwargs):
            return {}

    with pytest.raises(SourceExhaustedError):
        Empty()._try_sources("player_stats")


def test_single_source_dict_result_success():
    adapter = StubAdapter({"api": {"points": 25.3, "games": 82}})
    out = adapter._try_sources("player_stats")
    assert out["below_threshold"] is False
    assert out["result"]["points"] == 25.3


def test_min_records_override():
    class HighBarAdapter(BaseSportAdapter):
        sources = ["src"]

        def min_records(self, query_type: str) -> int:
            return 50  # needs 50 records

        def _fetch_from(self, source, query_type, **kwargs):
            return [{"g": i} for i in range(20)]  # only 20

    out = HighBarAdapter()._try_sources("player_game_log")
    assert out["below_threshold"] is True


def test_is_meaningful_default():
    class SimpleAdapter(BaseSportAdapter):
        sources = ["s"]

        def _fetch_from(self, source, query_type, **kwargs):
            return {}

    a = SimpleAdapter()
    assert not a.is_meaningful("player_stats", {})
    assert a.is_meaningful("player_stats", {"pts": 20})
    assert not a.is_meaningful("player_game_log", [])
    assert a.is_meaningful("player_game_log", [{"g": 1}])
