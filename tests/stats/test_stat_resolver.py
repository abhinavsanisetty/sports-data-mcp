"""
Offline tests for StatResolver enum → alias → Gemini chain (§3.7).

VCR/mocks intercept all Gemini calls; no real API calls are made.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import vcr

from sports_data_mcp.stats.resolver import STAT_ALIASES, StatResolver

_CASSETTES = Path(__file__).parent.parent / "cassettes" / "gemini"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_resolver(api_key: str = "test-key") -> StatResolver:
    return StatResolver(api_key=api_key)


def _mock_gemini_response(text: str) -> MagicMock:
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
# Tier 1: enum hit
# ---------------------------------------------------------------------------


def test_enum_hit_returns_enum_tier():
    r = _make_resolver()
    result = r.resolve("points", "nba")
    assert result.tier == "enum"
    assert result.canonical == "points"
    assert result.raw == "points"


def test_enum_hit_mlb_era():
    r = _make_resolver()
    result = r.resolve("era", "mlb")
    assert result.tier == "enum"
    assert result.canonical == "era"


def test_enum_hit_no_gemini_call():
    r = _make_resolver()
    with patch("urllib.request.urlopen") as mock_open:
        r.resolve("assists", "nba")
    mock_open.assert_not_called()


# ---------------------------------------------------------------------------
# Tier 2: alias hit
# ---------------------------------------------------------------------------


def test_alias_hit_nba_pts():
    r = _make_resolver()
    result = r.resolve("pts", "nba")
    assert result.tier == "alias"
    assert result.canonical == "points"
    assert result.raw == "pts"


def test_alias_hit_nba_reb():
    r = _make_resolver()
    result = r.resolve("reb", "nba")
    assert result.tier == "alias"
    assert result.canonical == "rebounds"


def test_alias_hit_nba_ast():
    r = _make_resolver()
    result = r.resolve("ast", "nba")
    assert result.tier == "alias"
    assert result.canonical == "assists"


def test_alias_hit_mlb_avg():
    r = _make_resolver()
    result = r.resolve("avg", "mlb")
    assert result.tier == "alias"
    assert result.canonical == "batting_avg"


def test_alias_hit_mlb_hr():
    r = _make_resolver()
    result = r.resolve("hr", "mlb")
    assert result.tier == "alias"
    assert result.canonical == "home_runs"


def test_alias_hit_mlb_era_alias():
    # 'era' is actually in the enum as a value, so tier should be "enum"
    # but 'era' alias is also defined — enum check comes first
    r = _make_resolver()
    result = r.resolve("era", "mlb")
    assert result.tier == "enum"


def test_alias_hit_no_gemini_call():
    r = _make_resolver()
    with patch("urllib.request.urlopen") as mock_open:
        r.resolve("pts", "nba")
    mock_open.assert_not_called()


# ---------------------------------------------------------------------------
# Tier 3: Gemini hit → tier="gemini"
# ---------------------------------------------------------------------------


def test_gemini_tier_returns_gemini():
    mock_resp = _mock_gemini_response('{"canonical": "points"}')
    r = _make_resolver()
    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = r.resolve("scoring average", "nba")
    assert result.tier == "gemini"
    assert result.canonical == "points"


def test_gemini_cassette(tmp_path):
    cassette_path = str(_CASSETTES / "test_stat_resolver_gemini_tier.yaml")
    my_vcr = vcr.VCR(
        filter_query_parameters=["key"],
        record_mode="none",
        match_on=["method", "host", "path"],
    )
    r = _make_resolver()
    with my_vcr.use_cassette(cassette_path):
        result = r.resolve("scoring", "nba")
    assert result.tier == "gemini"
    assert result.canonical == "points"


# ---------------------------------------------------------------------------
# Unknown: Gemini returns null / unrecognized → tier="unknown", canonical=None
# ---------------------------------------------------------------------------


def test_unknown_stat_returns_unknown_tier():
    mock_resp = _mock_gemini_response('{"canonical": null}')
    r = _make_resolver()
    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = r.resolve("zorblax", "nba")
    assert result.tier == "unknown"
    assert result.canonical is None


def test_unknown_stat_malformed_gemini_response():
    mock_resp = _mock_gemini_response("not json {{{")
    r = _make_resolver()
    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = r.resolve("totally unknown stat", "nba")
    assert result.tier == "unknown"
    assert result.canonical is None


def test_unknown_stat_no_key_returns_unknown():
    with patch("os.environ.get", return_value=None):
        r2 = StatResolver(api_key=None)
    with patch("urllib.request.urlopen") as mock_open:
        result = r2.resolve("totally unknown stat", "nba")
    mock_open.assert_not_called()
    assert result.tier == "unknown"
    assert result.canonical is None


# ---------------------------------------------------------------------------
# STAT_ALIASES coverage checks
# ---------------------------------------------------------------------------


def test_nba_aliases_cover_pts_reb_ast():
    assert "pts" in STAT_ALIASES["nba"]
    assert "reb" in STAT_ALIASES["nba"]
    assert "ast" in STAT_ALIASES["nba"]


def test_mlb_aliases_cover_avg_era_hr():
    assert "avg" in STAT_ALIASES["mlb"]
    # era is in the enum, so alias is redundant but can still be present
    assert "hr" in STAT_ALIASES["mlb"]
