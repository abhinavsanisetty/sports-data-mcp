# sports-data-mcp

Open-source Python MCP server that gives AI agents StatMuse-style historical sports query access across all major sports (NBA, NFL, MLB, NHL, soccer, NCAA). No live data — historical and analytical only. Completely free to use — only requires a free `GEMINI_API_KEY` from Google AI Studio (ai.google.dev, 30 seconds to obtain).

## Start here

**The full design plan is at:** `/Users/abhinavsanisetty/.claude/plans/tender-cooking-tulip.md`

That document is the source of truth. It contains ~75 deliberate design decisions across:
- Part 1: Foundational decisions (language, scope, data strategy, etc.)
- Part 2: Resilience (rate limits, name resolution, cache integrity, source fallback)
- Part 3: Evaluation & testing (unit/adapter/integration/golden/NL eval/cross-source + dev tooling)
- Part 4: Runtime & architecture (security, observability, concurrency, MCP pitfalls)
- Part 5: Implementation Plan (file structure, sources per sport, env vars, **Phase 0–7 build order**, verification)

Each decision documents the choice, alternatives considered, and reasoning. Don't re-litigate closed decisions unless the user reopens them.

## Implementation order (eval-driven)

Start with **Phase 0 — Tool Contract** (§5.4). It defines the Pydantic models and stat enums that both eval generation and main implementation read from. Without this, the eval-driven workflow has a chicken-and-egg problem (this was Critical Issue 5 from the pre-implementation review).

Phase order:
0. Tool contract (`tools/contract.py`, `stats/canonical.py`, `types.py`) — ~150–300 lines, no logic
1. Eval datasets + golden facts (against the contract) — stub server returns "not_implemented" so harness is wired before code exists
2. Skeleton & infrastructure (cache, resilience, http_client, single_flight, server)
3. Name & stat resolution (Gemini-based)
4. First two adapters (NBA + MLB)
5. Remaining adapters (NFL, NHL, soccer, NCAA)
6. NL fallback tool
7. HTTP transport, CLI, polish, open-source paperwork

## Things to verify in Phase 0 (model IDs may need refresh)

- **Google Gemini Flash model ID** — verify the current latest Gemini Flash against Google docs (ai.google.dev) and set it as the default for both `SPORTS_MCP_MODEL` and `SPORTS_MCP_EVAL_GENERATOR_MODEL`

Both env vars use the same model. Currently set to `gemini-2.0-flash` — update if a newer stable snapshot exists.

## How the user wants to work

- They want to be consulted on non-trivial design decisions (their preferred style — see project memory `feedback-planning-style`)
- For each design choice, present options + pros/cons rather than deciding unilaterally
- Direct, concise communication preferred

## Critical decisions you must not silently change

- One adapter file per sport with internal fallback chains (§1.10) — but HTTP infra is shared via `http_client.py` per host
- Per-host rate limits & circuit breakers (§2.1) — not per-adapter
- SQLite cache with `CACHE_VERSION` versioned keys + clear CLI (§2.4)
- Canonical core + typed per-sport extension schema (§3.34, closes Open Q 4.2)
- Cache write rule: write only if `is_meaningful(result) AND not _meta.below_threshold` (§4.7 revised)
- NL eval runs nightly with gate + cheap smoke on PR (§3.16 revised after Opus review) — NOT per-PR with real Gemini
- Integration test failures categorized: code = hard fail, source = soft fail (§3.8 revised)
- On query timeout, single-flight worker continues to completion — no separate prefetch (§4.5.c revised)

## Project working directory

This file lives at `/Users/abhinavsanisetty/Sports MCP Server/`. Code will live under `src/sports_data_mcp/` per the §5.1 file structure.

## When in doubt

Read the plan section relevant to the decision in question. If something seems contradictory or under-specified, ask the user before making a unilateral call.
