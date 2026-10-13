from __future__ import annotations

import subprocess
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _is_ignored(relative_path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--quiet", relative_path],
        cwd=REPOSITORY_ROOT,
        check=False,
    )
    return result.returncode == 0


def test_venue_data_and_large_artifact_paths_are_ignored() -> None:
    ignored = (
        ".codex/settings.json",
        ".github/workflows/ci.yml",
        ".superpowers/session/state.json",
        "tests/test_presentation_deck.py",
        "benchmark/catalog/kdd_public_release.yaml",
        "docs/superpowers/plans/2026-10-12-kdd-plan.md",
        "benchmark/data/heldout/raw/example.csv",
        "benchmark/data/heldout/raw/example.json",
        "datasets/sample.parquet",
        "models/checkpoint.ckpt",
        "release/archive.tar.gz",
        "presentation/slides.pptx",
        "benchmark/external/example/.git/objects/pack/data.pack",
        "benchmark/external/example/output/results.csv",
        "benchmark/external/regression_msr_official/regr.py",
        "benchmark/external/svarm_official/svarm.py",
        ".research_data_valuation_pricing_20260928/notes.md",
        ".archive/benchmark_iterations/snapshot.json",
    )

    assert [path for path in ignored if not _is_ignored(path)] == []


def test_source_configuration_and_small_fixtures_remain_trackable() -> None:
    trackable = (
        "benchmark/src/datamechbench/runner.py",
        "benchmark/configs/full.yaml",
        "benchmark/data/external/example/README.md",
        "benchmark/data/heldout/raw/example-source-receipt.json",
        "data/examples/stage0_records.jsonl",
        "data/examples/text.jsonl",
        "benchmark/submission_template/results.jsonl",
        "benchmark/outputs/.gitkeep",
    )

    assert [path for path in trackable if _is_ignored(path)] == []
