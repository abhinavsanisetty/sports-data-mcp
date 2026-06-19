"""
Environment variable loading and validation (§4.3.b, §4.3.c, §5.3).

Config is read exactly once at startup into an immutable Config object.
GEMINI_API_KEY is masked in repr to prevent accidental log leaks.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

logger = logging.getLogger(__name__)

_DEFAULT_CACHE_PATH = Path.home() / ".sports-data-mcp" / "cache.db"
_DEFAULT_MODEL = "gemini-2.0-flash"
_DEFAULT_LOG_LEVEL = "INFO"
_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_VALID_TRANSPORTS = {"stdio", "http"}


class Config(BaseModel):
    """Immutable runtime config loaded from environment variables.

    ``gemini_api_key`` is optional: the server must be able to start and serve
    structured tools when the agent supplies already-canonical names (§2.2).
    Name/stat resolution and the NL tool degrade gracefully when it is absent.
    """

    gemini_api_key: str | None = None
    model: str = _DEFAULT_MODEL
    eval_generator_model: str = _DEFAULT_MODEL
    cache_path: Path = Field(default=_DEFAULT_CACHE_PATH)
    cache_version: str = "v1"
    log_level: str = _DEFAULT_LOG_LEVEL
    transport: Literal["stdio", "http"] = "stdio"
    http_port: int = 8000
    max_records: int = 500
    query_timeout_sec: int = 25
    allow_unsafe_path: bool = False

    model_config = {"frozen": True}

    def __repr__(self) -> str:
        masked = "***" if self.gemini_api_key else "(not set)"
        return (
            f"Config(model={self.model!r}, cache_path={self.cache_path!r}, "
            f"transport={self.transport!r}, gemini_api_key={masked})"
        )

    # Pydantic v2 generates __str__ independently of __repr__; without this
    # override, str()/f-strings/print() render every field — including
    # gemini_api_key in cleartext — leaking the key (§4.3.b).
    def __str__(self) -> str:
        return self.__repr__()

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        upper = v.upper()
        if upper not in _VALID_LOG_LEVELS:
            raise ValueError(f"SPORTS_MCP_LOG_LEVEL must be one of {_VALID_LOG_LEVELS}, got {v!r}")
        return upper

    @field_validator("transport")
    @classmethod
    def _validate_transport(cls, v: str) -> str:
        if v not in _VALID_TRANSPORTS:
            raise ValueError(
                f"SPORTS_MCP_TRANSPORT must be one of {_VALID_TRANSPORTS}, got {v!r}"
            )
        return v

    @model_validator(mode="after")
    def _validate_cache_path(self) -> Config:
        path = self.cache_path.resolve()
        # Reject paths with ".." in original (post-resolve they're gone, but reject intent)
        if ".." in str(self.cache_path):
            raise ValueError(
                f"SPORTS_MCP_CACHE_PATH must not contain '..' segments: {self.cache_path}"
            )
        if not self.allow_unsafe_path:
            home = Path.home().resolve()
            try:
                path.relative_to(home)
            except ValueError:
                raise ValueError(
                    f"SPORTS_MCP_CACHE_PATH {path!r} is outside the home directory. "
                    "Set SPORTS_MCP_ALLOW_UNSAFE_PATH=1 to override."
                ) from None
        parent = path.parent
        if not parent.exists():
            try:
                parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise ValueError(
                    f"Cannot create cache directory {parent}: {exc}. "
                    "Check permissions or set SPORTS_MCP_CACHE_PATH to a writeable location."
                ) from exc
        if parent.exists() and not os.access(parent, os.W_OK):
            raise ValueError(
                f"Cache directory {parent} is not writeable. "
                "Check permissions or set SPORTS_MCP_CACHE_PATH to a writeable location."
            )
        return self


def _env(key: str, default: str | None = None) -> str | None:
    return os.environ.get(key, default)


def load_config() -> Config:
    """Load and validate config from environment. Raises ValueError with clear messages."""
    api_key = _env("GEMINI_API_KEY")
    if not api_key:
        # Not fatal: structured tools still work when the agent supplies
        # canonical names (§2.2). Name/stat resolution and the NL tool degrade
        # gracefully (returning an "ambiguous"/"unknown" hint) without a key.
        logger.warning(
            "GEMINI_API_KEY is not set. Name/stat resolution and the NL tool "
            "will be disabled; structured tools require canonical names. "
            "Get a free key at https://ai.google.dev (1500 req/day free tier)."
        )

    raw_cache = _env("SPORTS_MCP_CACHE_PATH")
    cache_path = Path(raw_cache) if raw_cache else _DEFAULT_CACHE_PATH

    allow_unsafe = _env("SPORTS_MCP_ALLOW_UNSAFE_PATH", "").lower() in {"1", "true", "yes"}

    cfg = Config(
        gemini_api_key=api_key,
        model=_env("SPORTS_MCP_MODEL", _DEFAULT_MODEL),
        eval_generator_model=_env("SPORTS_MCP_EVAL_GENERATOR_MODEL", _DEFAULT_MODEL),
        cache_path=cache_path,
        cache_version=_env("SPORTS_MCP_CACHE_VERSION", "v1"),
        log_level=_env("SPORTS_MCP_LOG_LEVEL", _DEFAULT_LOG_LEVEL),
        transport=_env("SPORTS_MCP_TRANSPORT", "stdio"),
        http_port=int(_env("SPORTS_MCP_HTTP_PORT", "8000")),
        max_records=int(_env("SPORTS_MCP_MAX_RECORDS", "500")),
        query_timeout_sec=int(_env("SPORTS_MCP_QUERY_TIMEOUT_SEC", "25")),
        allow_unsafe_path=allow_unsafe,
    )
    logger.info("Config loaded: %r", cfg)
    return cfg


if __name__ == "__main__":
    import sys

    sys.path.insert(0, "src")
    # Smoke test: load succeeds when GEMINI_API_KEY is set, fails cleanly when not.
    if not os.environ.get("GEMINI_API_KEY"):
        os.environ["GEMINI_API_KEY"] = "test-key"
        os.environ["SPORTS_MCP_CACHE_PATH"] = str(Path.home() / ".sports-data-mcp" / "cache.db")
    cfg = load_config()
    assert cfg.gemini_api_key == "test-key"
    assert "***" in repr(cfg)
    assert cfg.log_level == "INFO"
    print("config smoke test: PASS")
