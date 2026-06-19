"""
Name resolver: exact fast path → cache → Gemini fallback (§2.2, §4.3.b).

Public API: resolve(name, sport) -> ResolvedName
Fast path: checks _KNOWN_ENTITIES dict; Phase 4 populates it per adapter.
Gemini path: wraps name in <entity_name> delimiters per §4.3.b, requests JSON
  with canonical_name/entity_type/alternatives, Pydantic-parses response.
Cache: tool="name_resolution" via cache.py.
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.request
from typing import Literal

from pydantic import BaseModel, ValidationError

from sports_data_mcp.cache import Cache
from sports_data_mcp.types import SportLiteral

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# API key redaction (§4.3.b) — scrubs AIza* patterns from all log records
# ---------------------------------------------------------------------------

_KEY_PATTERN = re.compile(r"AIza[0-9A-Za-z\-_]{10,}")


class _RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _KEY_PATTERN.sub("***", record.msg)
        if record.args:
            if isinstance(record.args, tuple):
                record.args = tuple(
                    _KEY_PATTERN.sub("***", a) if isinstance(a, str) else a
                    for a in record.args
                )
            elif isinstance(record.args, dict):
                record.args = {
                    k: (_KEY_PATTERN.sub("***", v) if isinstance(v, str) else v)
                    for k, v in record.args.items()
                }
        return True


logger.addFilter(_RedactFilter())

# ---------------------------------------------------------------------------
# Known entities — Phase 4 populates this per adapter
# Keys: (name.lower().strip(), sport) → (canonical_name, entity_type)
# ---------------------------------------------------------------------------

_KNOWN_ENTITIES: dict[tuple[str, str], tuple[str, str]] = {}


def register_known_entity(
    name: str, sport: str, canonical: str, entity_type: str
) -> None:
    """Register a known entity for fast-path resolution (called by adapters)."""
    _KNOWN_ENTITIES[(name.lower().strip(), sport)] = (canonical, entity_type)


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


class ResolvedName(BaseModel):
    canonical: str
    sport: SportLiteral
    entity_type: Literal["player", "team"]
    confidence: Literal["exact", "gemini", "ambiguous"]
    candidates: list[str] | None = None


# ---------------------------------------------------------------------------
# Internal Gemini response model
# ---------------------------------------------------------------------------


class _GeminiNameResponse(BaseModel):
    canonical_name: str
    entity_type: Literal["player", "team"]
    alternatives: list[str] = []


# ---------------------------------------------------------------------------
# Gemini prompt
# ---------------------------------------------------------------------------

_GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
_DEFAULT_MODEL = "gemini-2.0-flash"

_PROMPT_TEMPLATE = (
    "You are a sports entity resolver. Given a name, return the canonical full name.\n\n"
    "Sport: {sport}\n"
    "Input: <entity_name>{name}</entity_name>\n\n"
    "Respond with JSON only (no markdown, no extra text):\n"
    '{{\n'
    '  "canonical_name": "<full official name>",\n'
    '  "entity_type": "player" or "team",\n'
    '  "alternatives": ["<other plausible match if ambiguous>"]\n'
    "}}\n\n"
    "If the name could refer to multiple entities, list all in alternatives."
)


# ---------------------------------------------------------------------------
# Resolver class
# ---------------------------------------------------------------------------


class NameResolver:
    """Resolves player/team names to canonical form. Never raises."""

    def __init__(
        self,
        cache: Cache,
        *,
        api_key: str | None = None,
        model: str = _DEFAULT_MODEL,
    ) -> None:
        self._cache = cache
        self._api_key = api_key if api_key is not None else os.environ.get("GEMINI_API_KEY")
        self._model = model

    def resolve(self, name: str, sport: str) -> ResolvedName:
        """Resolve *name* to canonical form for *sport*. Never raises."""
        # Fast path: exact match against known entities
        key = (name.lower().strip(), sport)
        if key in _KNOWN_ENTITIES:
            canonical, entity_type = _KNOWN_ENTITIES[key]
            return ResolvedName(
                canonical=canonical,
                sport=sport,  # type: ignore[arg-type]
                entity_type=entity_type,  # type: ignore[arg-type]
                confidence="exact",
            )

        # Cache check
        cache_args = {"name": name, "sport": sport}
        cached = self._cache.get("name_resolution", cache_args)
        if cached is not None:
            try:
                return ResolvedName.model_validate(cached)
            except (ValidationError, Exception):
                logger.debug("Corrupt name_resolution cache entry for %r; refetching.", name)

        # API key required from here
        if not self._api_key:
            return ResolvedName(
                canonical=name,
                sport=sport,  # type: ignore[arg-type]
                entity_type="player",
                confidence="ambiguous",
                candidates=[
                    "GEMINI_API_KEY is required for name resolution; "
                    "supply a canonical name or set GEMINI_API_KEY"
                ],
            )

        # Gemini path
        resolved = self._call_gemini(name, sport)
        if resolved.confidence == "gemini":
            self._cache.set("name_resolution", cache_args, resolved.model_dump())
        return resolved

    def _call_gemini(self, name: str, sport: str) -> ResolvedName:
        """Call Gemini REST API and parse response. On any failure, return ambiguous."""
        prompt = _PROMPT_TEMPLATE.format(name=name, sport=sport)
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
            # Strip markdown code fences if Gemini wraps output in them
            text = re.sub(r"^```[a-z]*\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            parsed = _GeminiNameResponse.model_validate(json.loads(text))
            return ResolvedName(
                canonical=parsed.canonical_name,
                sport=sport,  # type: ignore[arg-type]
                entity_type=parsed.entity_type,
                confidence="gemini",
                candidates=parsed.alternatives if parsed.alternatives else None,
            )
        except Exception as exc:
            logger.warning("Gemini name resolution failed for %r/%s: %s", name, sport, exc)
            return ResolvedName(
                canonical=name,
                sport=sport,  # type: ignore[arg-type]
                entity_type="player",
                confidence="ambiguous",
                candidates=None,
            )
