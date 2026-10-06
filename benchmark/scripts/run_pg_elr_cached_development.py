#!/usr/bin/env python3
"""Run and resume the strict PG-ELR development matrix on cached real games."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from datamechbench.elr_selection import leave_one_dataset_out_select, write_selection_record
from datamechbench.pg_elr_development import (
    DIRECT_METHODS,
    amortized_envelope_summary,
    append_result_rows,
    candidate_grid,
    iter_development_rows,
    load_real_development_games,
    read_result_rows,
    selection_rows,
)


def _integers(spec: str) -> tuple[int, ...]:
    if ":" in spec:
        start, stop = (int(value) for value in spec.split(":", 1))
        return tuple(range(start, stop))
    return tuple(int(value) for value in spec.split(",") if value)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cache-root",
        type=Path,
        default=Path("outputs/elr_vrds_real_core"),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("outputs/pg_elr_paper/development_cached"),
    )
    parser.add_argument("--budgets", default="192,224")
    parser.add_argument("--seeds", default="0:100")
    parser.add_argument("--setting-ids")
    parser.add_argument("--ratio-kind", choices=("q1", "median", "q3"), default="median")
    parser.add_argument("--flush-every", type=int, default=25)
    args = parser.parse_args()

    games = load_real_development_games(args.cache_root)
    if args.setting_ids:
        requested = set(args.setting_ids.split(","))
        games = tuple(item for item in games if item.game.setting_id in requested)
        missing = requested - {item.game.setting_id for item in games}
        if missing:
            raise ValueError(f"unknown or incomplete settings: {sorted(missing)}")
    configs = candidate_grid()
    execution_methods = (*DIRECT_METHODS, "pg_elr", "pg_elr_adaptive_direct")
    raw_path = args.output_root / "raw_results.jsonl"
    existing = read_result_rows(raw_path)
    completed_ids = {row["run_id"] for row in existing}
    batch = []
    added = 0
    for row in iter_development_rows(
        games,
        budgets=_integers(args.budgets),
        seeds=_integers(args.seeds),
        direct_methods=execution_methods,
        configs=configs,
        ratio_kind=args.ratio_kind,
        completed_run_ids=completed_ids,
    ):
        batch.append(row)
        if len(batch) >= args.flush_every:
            added += append_result_rows(raw_path, batch)
            batch.clear()
    added += append_result_rows(raw_path, batch)

    all_rows = read_result_rows(raw_path)
    current_methods = {*execution_methods, "bd_pg_elr"}
    current_rows = [row for row in all_rows if row.get("method_id") in current_methods]
    selected_rows, baselines = selection_rows(current_rows, direct_methods=DIRECT_METHODS)
    envelope = amortized_envelope_summary(current_rows, direct_methods=DIRECT_METHODS)
    summary = leave_one_dataset_out_select(selected_rows, candidate_grid=configs)
    args.output_root.mkdir(parents=True, exist_ok=True)
    (args.output_root / "candidate_report.json").write_text(
        json.dumps(
            {
                "summary": asdict(summary),
                "strongest_direct_method_by_cell": baselines,
                "amortized_envelope": envelope,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    source = Path(__file__).parents[1] / "src/datamechbench/pg_elr_development.py"
    selection_hash = write_selection_record(
        summary,
        args.output_root / "selection_record.json",
        source_hashes={
            "development_module": _sha256(source),
            "raw_results": _sha256(raw_path),
        },
    )
    expected = len(games) * len(_integers(args.budgets)) * len(_integers(args.seeds)) * (
        len(execution_methods) + len(configs)
    )
    manifest = {
        "schema_version": "1.0",
        "scope": "existing_real_game_screening",
        "games": [item.game.setting_id for item in games],
        "game_hashes": [item.game.high.content_hash for item in games],
        "budgets": list(_integers(args.budgets)),
        "seeds": list(_integers(args.seeds)),
        "direct_methods": list(DIRECT_METHODS),
        "amortized_methods": ["pg_elr", "pg_elr_adaptive_direct"],
        "candidate_configs": [asdict(config) for config in configs],
        "ratio_kind": args.ratio_kind,
        "expected_rows": expected,
        "observed_rows": len(current_rows),
        "superseded_rows_retained": len(all_rows) - len(current_rows),
        "new_rows": added,
        "selection_hash": selection_hash,
        "complete": len(current_rows) == expected,
    }
    (args.output_root / "study_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(manifest, sort_keys=True))


if __name__ == "__main__":
    main()
