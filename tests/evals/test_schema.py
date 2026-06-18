from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests.evals.models import GoldenFact, SeedQuestion

EVALS_DIR = Path(__file__).parent
GOLDEN_DIR = EVALS_DIR.parent / "golden"
SEEDS_PATH = EVALS_DIR / "seeds.yaml"

SPORTS = ["nba", "nfl", "mlb", "nhl", "soccer", "ncaa"]
TOOL_CATEGORIES = [
    "player_stats",
    "player_game_log",
    "team_stats",
    "team_game_log",
    "league_leaders",
    "team_history",
]


def load_seeds() -> list[SeedQuestion]:
    raw = yaml.safe_load(SEEDS_PATH.read_text())
    return [SeedQuestion.model_validate(entry) for entry in raw]


def test_seeds_load_and_validate():
    seeds = load_seeds()
    assert len(seeds) >= 50, f"Expected >= 50 seeds, got {len(seeds)}"


def test_seeds_cover_all_36_cells():
    seeds = load_seeds()
    covered = {(s.sport, s.tool_category) for s in seeds}
    missing = [(sp, tc) for sp in SPORTS for tc in TOOL_CATEGORIES if (sp, tc) not in covered]
    assert not missing, f"Missing cells: {missing}"


def test_seed_ids_unique():
    seeds = load_seeds()
    ids = [s.id for s in seeds]
    dupes = [i for i in ids if ids.count(i) > 1]
    assert not dupes, f"Duplicate seed ids: {set(dupes)}"


@pytest.mark.parametrize("sport", ["nba", "mlb"])
def test_golden_loads_and_validates(sport: str):
    golden_path = GOLDEN_DIR / f"{sport}.yaml"
    raw = yaml.safe_load(golden_path.read_text())
    facts = [GoldenFact.model_validate(entry) for entry in raw]
    assert len(facts) >= 50, f"Expected >= 50 golden facts for {sport}, got {len(facts)}"


@pytest.mark.parametrize("sport", ["nba", "mlb"])
def test_golden_ids_unique(sport: str):
    golden_path = GOLDEN_DIR / f"{sport}.yaml"
    raw = yaml.safe_load(golden_path.read_text())
    facts = [GoldenFact.model_validate(entry) for entry in raw]
    ids = [f.fact_id for f in facts]
    dupes = [i for i in ids if ids.count(i) > 1]
    assert not dupes, f"Duplicate fact_ids in {sport}: {set(dupes)}"
