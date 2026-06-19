"""Tests for config.py: API-key masking (§4.3.b) and cache-path sanitization (§4.3.c)."""
from __future__ import annotations

import sys

sys.path.insert(0, "src")

from pathlib import Path

import pytest

from sports_data_mcp.config import Config

_FAKE_KEY = "AIzaSyTESTKEY1234567890abcdefghijKLMNOP"


def _config(**overrides) -> Config:
    base = {
        "gemini_api_key": _FAKE_KEY,
        "cache_path": Path.home() / ".sports-data-mcp" / "cache.db",
    }
    base.update(overrides)
    return Config(**base)


# ---------------------------------------------------------------------------
# §4.3.b — the key must never appear in repr / str / f-string
# ---------------------------------------------------------------------------


def test_repr_masks_key():
    cfg = _config()
    assert _FAKE_KEY not in repr(cfg)
    assert "***" in repr(cfg)


def test_str_masks_key():
    # Pydantic v2 generates __str__ independently of __repr__; this guards the
    # regression where str(cfg) rendered every field in cleartext.
    cfg = _config()
    assert _FAKE_KEY not in str(cfg)


def test_fstring_masks_key():
    cfg = _config()
    assert _FAKE_KEY not in f"{cfg}"


# ---------------------------------------------------------------------------
# §4.3.c — cache path sanitization
# ---------------------------------------------------------------------------


def test_rejects_dotdot_segments():
    with pytest.raises(ValueError, match=r"\.\."):
        _config(cache_path=Path.home() / ".." / "evil" / "cache.db")


def test_rejects_path_outside_home_by_default():
    with pytest.raises(ValueError, match="outside the home directory"):
        _config(cache_path=Path("/tmp/cache.db"))


def test_allows_outside_home_with_unsafe_opt_out(tmp_path):
    # tmp_path is typically outside ~; opt-out must permit it.
    cfg = _config(cache_path=tmp_path / "cache.db", allow_unsafe_path=True)
    assert cfg.allow_unsafe_path is True
