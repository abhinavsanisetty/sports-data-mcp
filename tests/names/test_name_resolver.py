"""
Offline tests for NameResolver (§3.7).

All Gemini calls are intercepted — either via VCR cassette or unittest.mock.
No real API calls are made.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import vcr

from sports_data_mcp.cache import Cache
from sports_data_mcp.names.resolver import (
    _KNOWN_ENTITIES,
    NameResolver,
    ResolvedName,
    register_known_entity,
)

_CASSETTES = Path(__file__).parent.parent / "cassettes" / "gemini"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_resolver(tmp_path, api_key="test-key") -> NameResolver:
    cache = Cache(db_path=tmp_path / "cache.db", cache_version="v1")
    return NameResolver(cache, api_key=api_key)


def _make_gemini_response(text: str) -> MagicMock:
    """Build a mock urllib response returning *text* as the Gemini JSON body."""
    mock_resp = MagicMock()
    body = json.dumps({
        "candidates": [{
            "content": {"parts": [{"text": text}], "role": "model"},
            "finishReason": "STOP",
        }]
    }).encode()
    mock_resp.read.return_value = body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


# ---------------------------------------------------------------------------
# Fixtures: stub known-entities with 2 entries
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_known_entities():
    """Clear and re-populate known entities before each test."""
    _KNOWN_ENTITIES.clear()
    register_known_entity("michael jordan", "nba", "Michael Jordan", "player")
    register_known_entity("chicago bulls", "nba", "Chicago Bulls", "team")
    yield
    _KNOWN_ENTITIES.clear()


# ---------------------------------------------------------------------------
# Test: exact fast path (no Gemini call)
# ---------------------------------------------------------------------------


def test_exact_fast_path_player(tmp_path):
    resolver = _make_resolver(tmp_path)
    with patch("urllib.request.urlopen") as mock_open:
        result = resolver.resolve("Michael Jordan", "nba")
    mock_open.assert_not_called()
    assert result.confidence == "exact"
    assert result.canonical == "Michael Jordan"
    assert result.entity_type == "player"


def test_exact_fast_path_team(tmp_path):
    resolver = _make_resolver(tmp_path)
    with patch("urllib.request.urlopen") as mock_open:
        result = resolver.resolve("Chicago Bulls", "nba")
    mock_open.assert_not_called()
    assert result.confidence == "exact"
    assert result.canonical == "Chicago Bulls"
    assert result.entity_type == "team"


# ---------------------------------------------------------------------------
# Test: Gemini path → confidence="gemini"
# ---------------------------------------------------------------------------


def test_gemini_path_returns_gemini_confidence(tmp_path):
    gemini_json = '{"canonical_name": "Stephen Curry", "entity_type": "player", "alternatives": []}'
    mock_resp = _make_gemini_response(gemini_json)
    resolver = _make_resolver(tmp_path)
    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = resolver.resolve("Steph Curry", "nba")
    assert result.confidence == "gemini"
    assert result.canonical == "Stephen Curry"
    assert result.entity_type == "player"


# ---------------------------------------------------------------------------
# Test: malformed JSON → confidence="ambiguous", no raise
# ---------------------------------------------------------------------------


def test_malformed_json_returns_ambiguous(tmp_path):
    mock_resp = _make_gemini_response("NOT JSON AT ALL {{{{")
    resolver = _make_resolver(tmp_path)
    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = resolver.resolve("Steph Curry", "nba")
    assert result.confidence == "ambiguous"
    assert result.canonical == "Steph Curry"  # falls back to raw input


def test_malformed_json_does_not_raise(tmp_path):
    mock_resp = _make_gemini_response("{")  # truncated JSON
    resolver = _make_resolver(tmp_path)
    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = resolver.resolve("Someone", "mlb")
    assert isinstance(result, ResolvedName)


# ---------------------------------------------------------------------------
# Test: absent API key → ambiguous + descriptive message
# ---------------------------------------------------------------------------


def test_absent_key_returns_ambiguous_with_message(tmp_path):
    resolver = _make_resolver(tmp_path, api_key=None)
    # Ensure env var is also absent
    with patch("os.environ.get", return_value=None):
        cache = Cache(db_path=tmp_path / "cache2.db", cache_version="v1")
        resolver = NameResolver(cache, api_key=None)
    with patch("urllib.request.urlopen") as mock_open:
        result = resolver.resolve("LeBron James", "nba")
    mock_open.assert_not_called()
    assert result.confidence == "ambiguous"
    assert result.candidates is not None
    assert len(result.candidates) > 0
    assert "GEMINI_API_KEY" in result.candidates[0]


# ---------------------------------------------------------------------------
# Test: cache hit skips Gemini
# ---------------------------------------------------------------------------


def test_cache_hit_skips_gemini(tmp_path):
    gemini_json = '{"canonical_name": "Kobe Bryant", "entity_type": "player", "alternatives": []}'
    mock_resp = _make_gemini_response(gemini_json)
    resolver = _make_resolver(tmp_path)

    # First call — Gemini fires, result cached
    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
        first = resolver.resolve("kobe", "nba")
    assert mock_open.call_count == 1
    assert first.confidence == "gemini"

    # Second call — cache hit, Gemini must NOT be called
    with patch("urllib.request.urlopen") as mock_open2:
        second = resolver.resolve("kobe", "nba")
    mock_open2.assert_not_called()
    assert second.confidence == "gemini"
    assert second.canonical == "Kobe Bryant"


# ---------------------------------------------------------------------------
# Test: VCR cassette — one real resolution replayed from cassette
# ---------------------------------------------------------------------------


def test_resolve_nba_cassette(tmp_path):
    cassette_path = str(_CASSETTES / "test_name_resolver_resolve_nba.yaml")
    my_vcr = vcr.VCR(
        filter_query_parameters=["key"],
        record_mode="none",
        match_on=["method", "host", "path"],
    )
    resolver = _make_resolver(tmp_path)
    with my_vcr.use_cassette(cassette_path):
        result = resolver.resolve("lebron james", "nba")
    assert result.confidence == "gemini"
    assert result.canonical == "LeBron James"
    assert result.entity_type == "player"


# ---------------------------------------------------------------------------
# Test: API key must not leak into logs even via an exception arg (§4.3.b)
# ---------------------------------------------------------------------------


def test_api_key_not_leaked_in_logs_on_failure(tmp_path, caplog):
    fake_key = "AIzaSyD1234567890abcdefGHIJKLmnopQRSTuv"
    cache = Cache(db_path=tmp_path / "cache.db", cache_version="v1")
    resolver = NameResolver(cache, api_key=fake_key)

    def _boom(*_a, **_k):
        # urllib failures stringify the API-keyed URL into the exception message
        raise OSError(
            "connection failed to "
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-2.0-flash:generateContent?key={fake_key}"
        )

    with caplog.at_level("DEBUG"), patch("urllib.request.urlopen", side_effect=_boom):
        result = resolver.resolve("steph curry", "nba")

    assert result.confidence == "ambiguous"  # never raises
    assert fake_key not in caplog.text
    assert "***" in caplog.text
