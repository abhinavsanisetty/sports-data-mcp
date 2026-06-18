from __future__ import annotations

from pathlib import Path

import yaml

from sports_data_mcp.stub import StubServer
from tests.evals.harness import run_harness


def test_all_seeds_fail_against_stub():
    result = run_harness(StubServer())
    assert result.passed == 0, f"Got {result.passed} passed — harness has false positives"
    assert result.failed == result.total
    assert result.score == 0.0


def test_one_seed_passes_stub_overridden():
    seeds_path = Path(__file__).parent / "seeds.yaml"
    raw = yaml.safe_load(seeds_path.read_text())
    first = raw[0]
    first_tool = first["expected_plan"]["tool"]
    first_args = first["expected_plan"]["args"]

    class PartialStub(StubServer):
        def call_tool(self, tool_name: str, args: dict) -> dict:
            if tool_name == first_tool and args == first_args:
                return {"status": "ok", "data": {"mocked": True}}
            return super().call_tool(tool_name, args)

    result = run_harness(PartialStub())
    assert result.passed == 1, f"Got {result.passed} passed — harness has false negatives"
    assert result.details[0]["passed"] is True
    assert all(not d["passed"] for d in result.details[1:])
