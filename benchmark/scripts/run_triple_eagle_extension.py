#!/usr/bin/env python3
"""Build or verify the post-freeze Triple Eagle procurement extension."""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from datamechbench.report import (
    write_jsonl,
    write_leaderboard_csvs,
    write_markdown_report,
    write_research_artifacts,
    write_track_csvs,
)
from datamechbench.runner import load_config, run_benchmark
from datamechbench.triple_eagle_analysis import (
    build_triple_eagle_extension_artifacts,
    verify_triple_eagle_extension_artifacts,
)

ROOT = Path(__file__).resolve().parents[2]
EXTENSION_CONFIG = ROOT / "benchmark/configs/kdd_triple_eagle_extension.yaml"
SUPPLEMENTAL_CONFIG = ROOT / "benchmark/configs/kdd_triple_eagle_baseline_completion.yaml"
BASELINE = ROOT / "benchmark/outputs/full/raw_results.jsonl"
ANALYSIS = ROOT / "benchmark/outputs/kdd_triple_eagle_extension/analysis"


def _run_config(path: Path) -> Path:
    config = load_config(path)
    # Runtime is environment noise, not part of this scientific extension.
    results = tuple(replace(row, runtime_seconds=0.0) for row in run_benchmark(config))
    output = ROOT / config.output_dir
    raw = write_jsonl(results, output / "raw_results.jsonl")
    write_track_csvs(results, output)
    write_leaderboard_csvs(results, output)
    write_research_artifacts(results, output, config_path=path)
    write_markdown_report(results, output / "report.md")
    return raw


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--build", action="store_true")
    mode.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.build:
        extension = _run_config(EXTENSION_CONFIG)
        supplemental = _run_config(SUPPLEMENTAL_CONFIG)
        build_triple_eagle_extension_artifacts(
            extension.relative_to(ROOT).as_posix(),
            BASELINE.relative_to(ROOT).as_posix(),
            ANALYSIS,
            supplemental_results=supplemental.relative_to(ROOT).as_posix(),
        )
    checked = verify_triple_eagle_extension_artifacts(
        ANALYSIS / "manifest.json", repository_root=ROOT
    )
    print(json.dumps(checked, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if checked["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
