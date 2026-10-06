#!/usr/bin/env python3
"""Build or verify the post-freeze BFM-VM procurement extension."""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from datamechbench.bfm_vm_analysis import (
    build_bfm_vm_extension_artifacts,
    verify_bfm_vm_extension_artifacts,
)
from datamechbench.report import (
    write_jsonl,
    write_leaderboard_csvs,
    write_markdown_report,
    write_research_artifacts,
    write_track_csvs,
)
from datamechbench.runner import load_config, run_benchmark

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "benchmark/configs/kdd_bfm_vm_extension.yaml"
OUTPUT = ROOT / "benchmark/outputs/kdd_bfm_vm_extension"
ANALYSIS = OUTPUT / "analysis"


def _run() -> Path:
    config = load_config(CONFIG)
    results = tuple(replace(row, runtime_seconds=0.0) for row in run_benchmark(config))
    raw = write_jsonl(results, OUTPUT / "raw_results.jsonl")
    write_track_csvs(results, OUTPUT)
    write_leaderboard_csvs(results, OUTPUT)
    write_research_artifacts(results, OUTPUT, config_path=CONFIG)
    write_markdown_report(results, OUTPUT / "report.md")
    return raw


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--build", action="store_true")
    mode.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.build:
        raw = _run()
        build_bfm_vm_extension_artifacts(
            raw,
            ROOT / "benchmark/outputs/full/raw_results.jsonl",
            ROOT / "benchmark/outputs/kdd_triple_eagle_extension/raw_results.jsonl",
            ROOT
            / "benchmark/outputs/kdd_triple_eagle_baseline_completion/raw_results.jsonl",
            ROOT / "benchmark/evidence/bfm_vm_source_audit_v1.json",
            ANALYSIS,
            repository_root=ROOT,
        )
    checked = verify_bfm_vm_extension_artifacts(
        ANALYSIS / "manifest.json", repository_root=ROOT
    )
    print(json.dumps(checked, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if checked["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
