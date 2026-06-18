#!/usr/bin/env python
"""
Eval question generator — Phase 1 (§3.14, §3.36).

Reads tests/evals/seeds.yaml, produces N=3 rephrased variants of each seed
via Gemini 2.0 Flash, and writes tests/evals/generated_raw.yaml with
review_status: pending on every entry.

Usage:
    python scripts/generate_evals.py [--dry-run] [--n 3] [--seeds PATH] [--out PATH]
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sports_data_mcp.stats.canonical import SPORT_STAT_ENUM
from sports_data_mcp.tools.contract import TOOL_ARGS_MAP

_REPO_ROOT = Path(__file__).parent.parent
_DEFAULT_SEEDS = _REPO_ROOT / "tests" / "evals" / "seeds.yaml"
_DEFAULT_OUT = _REPO_ROOT / "tests" / "evals" / "generated_raw.yaml"

_GENERATOR_MODEL = os.environ.get("SPORTS_MCP_EVAL_GENERATOR_MODEL", "gemini-2.0-flash")


def _tool_arg_fields(tool_name: str) -> list[str]:
    model = TOOL_ARGS_MAP.get(tool_name)
    if model is None:
        return []
    return list(model.model_fields.keys())


def _stat_names_for_sport(sport: str) -> list[str]:
    enum_cls = SPORT_STAT_ENUM.get(sport)
    if enum_cls is None:
        return []
    return [member.value for member in enum_cls]


def _build_prompt(seed: dict, n: int) -> str:
    tool = seed["expected_plan"]["tool"]
    args = seed["expected_plan"]["args"]
    arg_fields = _tool_arg_fields(tool)
    stat_names = _stat_names_for_sport(seed["sport"])

    lines = [
        f"You are generating eval questions for a sports data tool ({tool}).",
        "",
        f"Original question: {seed['question']}",
        f"Expected plan: tool={tool}, args={args}",
        "",
        f"Valid argument fields for {tool}: {arg_fields}",
        f"Valid canonical stat names for {seed['sport']}: {stat_names}",
        "",
        f"Generate exactly {n} rephrased variants of the original question.",
        "Rules:",
        "  - Each variant must have IDENTICAL expected_plan (same tool and args).",
        "  - Vary phrasing, word order, and conversational tone — not the facts.",
        "  - Do not introduce new stats, players, seasons, or teams.",
        "  - Output a YAML list with fields: question, phrasing (literal|conversational).",
        "  - Do not include any explanation or commentary — only the YAML list.",
    ]
    return "\n".join(lines)


def _call_gemini(prompt: str, api_key: str) -> str:
    import google.generativeai as genai  # type: ignore[import]

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(_GENERATOR_MODEL)
    response = model.generate_content(prompt)
    return response.text


def _parse_variants(raw_text: str, seed: dict, n: int) -> list[dict]:
    try:
        variants = yaml.safe_load(raw_text)
        if not isinstance(variants, list):
            variants = []
    except yaml.YAMLError:
        variants = []

    results = []
    for i, v in enumerate(variants[:n]):
        if not isinstance(v, dict) or "question" not in v:
            continue
        results.append(
            {
                "id": f"{seed['id']}.gen.{i + 1:02d}",
                "sport": seed["sport"],
                "tool_category": seed["tool_category"],
                "difficulty": seed.get("difficulty", "medium"),
                "phrasing": v.get("phrasing", "conversational"),
                "question": v["question"],
                "expected_plan": seed["expected_plan"],
                "review_status": "pending",
                "generator": _GENERATOR_MODEL,
                "generated_at": datetime.now(UTC).isoformat(),
                "source_seed_id": seed["id"],
            }
        )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print prompts, skip Gemini calls")
    parser.add_argument("--n", type=int, default=3, help="Variants per seed (default 3)")
    parser.add_argument("--seeds", type=Path, default=_DEFAULT_SEEDS)
    parser.add_argument("--out", type=Path, default=_DEFAULT_OUT)
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key and not args.dry_run:
        print("ERROR: GEMINI_API_KEY is not set. Set it or pass --dry-run.", file=sys.stderr)
        sys.exit(1)

    seeds = yaml.safe_load(args.seeds.read_text())
    all_generated: list[dict] = []

    for seed in seeds:
        prompt = _build_prompt(seed, args.n)

        if args.dry_run:
            print(f"\n{'=' * 60}")
            print(f"Seed: {seed['id']}")
            print(prompt)
            continue

        raw = _call_gemini(prompt, api_key)
        variants = _parse_variants(raw, seed, args.n)
        all_generated.extend(variants)

    if not args.dry_run:
        args.out.write_text(yaml.dump(all_generated, allow_unicode=True, sort_keys=False))
        print(f"Wrote {len(all_generated)} generated questions to {args.out}")


if __name__ == "__main__":
    main()
