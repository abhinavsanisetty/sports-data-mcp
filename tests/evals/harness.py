from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from tests.evals.models import SeedQuestion

_DEFAULT_SEEDS = Path(__file__).parent / "seeds.yaml"

_FAIL_STATUSES = {"not_implemented", "error", None}


@dataclass
class HarnessResult:
    total: int
    passed: int
    failed: int
    score: float
    details: list[dict] = field(default_factory=list)


def run_harness(server, seeds_path: Path = _DEFAULT_SEEDS) -> HarnessResult:
    raw = yaml.safe_load(Path(seeds_path).read_text())
    seeds = [SeedQuestion.model_validate(entry) for entry in raw]

    details = []
    passed = 0

    for seed in seeds:
        tool = seed.expected_plan.tool
        args = seed.expected_plan.args
        result = server.call_tool(tool, args)
        status = result.get("status") if isinstance(result, dict) else None
        ok = status not in _FAIL_STATUSES
        if ok:
            passed += 1
        details.append({"id": seed.id, "tool": tool, "status": status, "passed": ok})

    total = len(seeds)
    failed = total - passed
    score = passed / total if total > 0 else 0.0
    return HarnessResult(total=total, passed=passed, failed=failed, score=score, details=details)
