from __future__ import annotations

import json
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_ROOT = REPOSITORY_ROOT / "benchmark"


def test_benchmark_tree_contains_no_www_paper_pipeline() -> None:
    forbidden = (
        "www2027",
        "www_scr",
        "www_web_markets",
        "www_game_builders",
        "www_market_metrics",
        "scr_shapley_confirmatory",
        "scr_shapley_development",
    )
    paths = [
        path.relative_to(BENCHMARK_ROOT).as_posix().lower()
        for path in BENCHMARK_ROOT.rglob("*")
        if path.is_file()
        and "outputs" not in path.relative_to(BENCHMARK_ROOT).parts
        and "build" not in path.relative_to(BENCHMARK_ROOT).parts
        and "__pycache__" not in path.parts
    ]
    violations = [path for path in paths if any(token in path for token in forbidden)]
    assert violations == []


def test_kdd_manifest_does_not_bind_scr_or_www_research() -> None:
    path = BENCHMARK_ROOT / "reproduction" / "kdd2027_core_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    bound = json.dumps(manifest, sort_keys=True).lower()
    assert "www2027" not in bound
    assert "scr_shapley" not in bound
    assert "scr_confirmatory" not in bound


def test_decision_impact_has_only_benchmark_contract_layers() -> None:
    from datamechbench.decision_impact import DEFAULT_INPUTS

    assert set(DEFAULT_INPUTS) == {
        "confirmatory_contrasts",
        "constraint_profiles",
        "finite_incentives",
    }
