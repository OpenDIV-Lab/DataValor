#!/usr/bin/env python3
"""Run the frozen PG-ELR confirmation on complete real coalition games."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from dataclasses import asdict
from pathlib import Path

import numpy as np
from datamechbench.elr_statistics import (
    holm_comparison_family,
    paired_method_comparison,
)
from datamechbench.methods.valuation_multifidelity import BudgetDebitedConfig
from datamechbench.pg_elr_development import (
    DIRECT_METHODS,
    amortized_envelope_summary,
    append_result_rows,
    iter_development_rows,
    load_real_development_games,
    read_result_rows,
    selection_rows,
)
from datamechbench.real_experiment import authorize_pg_elr_confirmatory
from datamechbench.statistics import holm_adjust

BENCHMARK = Path(__file__).parents[1]
EXTERNAL_METHODS = (
    "official_stratified_svarm",
    "official_stratified_svarm_plus",
    "pydvl_vrds",
    "pydvl_owen",
    "pydvl_group_testing",
)
ALL_DIRECT_METHODS = (*DIRECT_METHODS, *EXTERNAL_METHODS)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_hashes() -> dict[str, str]:
    return {
        "selection_record": _sha256(BENCHMARK / "evidence/pg_elr/selection_record.json"),
        "method_source": _sha256(BENCHMARK / "src/datamechbench/methods/valuation_multifidelity.py"),
        "development_config": _sha256(BENCHMARK / "configs/pg_elr_paper_development.yaml"),
        "confirmatory_config": _sha256(BENCHMARK / "configs/pg_elr_paper_confirmatory.yaml"),
        "statistics_source": _sha256(BENCHMARK / "src/datamechbench/elr_statistics.py"),
        "report_template": _sha256(BENCHMARK / "docs/pg_elr_confirmatory_report_template.md"),
    }


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def _cell_key(row) -> tuple[str, str, int]:
    return str(row["dataset_id"]), str(row["partition"]), int(row["budget"])


def _baseline_by_cell(rows) -> dict[tuple[str, str, int], str]:
    chosen = {}
    for cell in sorted({_cell_key(row) for row in rows}):
        medians = []
        for method in ALL_DIRECT_METHODS:
            values = [
                float(row["score_mae"])
                for row in rows
                if _cell_key(row) == cell
                and row["method_id"] == method
                and row["status"] == "completed"
            ]
            if values:
                medians.append((statistics.median(values), ALL_DIRECT_METHODS.index(method), method))
        if medians:
            chosen[cell] = min(medians)[2]
    return chosen


def _comparisons(rows, baselines):
    comparisons = []
    for method in ("bd_pg_elr", "pg_elr", "pg_elr_adaptive_direct"):
        family = []
        cells = []
        for cell, baseline in sorted(baselines.items()):
            cell_rows = []
            for row in rows:
                if _cell_key(row) != cell or row["method_id"] not in {method, baseline}:
                    continue
                cell_rows.append(
                    {
                        **row,
                        "mae": row["score_mae"],
                        "estimator_seed": row["seed"],
                    }
                )
            family.append(
                paired_method_comparison(
                    cell_rows, method_id=method, baseline_id=baseline
                )
            )
            cells.append(cell)
        adjusted = holm_comparison_family(family)
        for cell, item in zip(cells, adjusted, strict=True):
            comparisons.append({"dataset_id": cell[0], "partition": cell[1], "budget": cell[2], **asdict(item)})
    return comparisons


def _downstream(rows, baselines):
    metric_paths = {
        "top1_utility_regret": ("top_k", "1", "exact_utility_regret"),
        "top1_owner_disagreement": ("top_k", "1", "selected_owner_disagreement"),
        "knapsack50_utility_regret": ("knapsack", "0.5", "exact_utility_regret"),
        "knapsack50_budget_violation": ("knapsack", "0.5", "budget_violation"),
        "sequential80_stopping_regret": ("sequential", "0.8", "stopping_regret"),
    }
    records = []
    p_values = []
    for method in ("bd_pg_elr", "pg_elr", "pg_elr_adaptive_direct"):
        for cell, baseline in sorted(baselines.items()):
            by_method = {
                name: {
                    int(row["seed"]): row
                    for row in rows
                    if _cell_key(row) == cell
                    and row["method_id"] == name
                    and row["status"] == "completed"
                    and row.get("market_metrics") is not None
                }
                for name in (method, baseline)
            }
            for metric, path in metric_paths.items():
                seeds = sorted(set(by_method[method]) & set(by_method[baseline]))
                left = np.asarray([
                    by_method[method][seed]["market_metrics"][path[0]][path[1]][path[2]]
                    for seed in seeds
                ], dtype=float)
                right = np.asarray([
                    by_method[baseline][seed]["market_metrics"][path[0]][path[1]][path[2]]
                    for seed in seeds
                ], dtype=float)
                if not len(seeds):
                    continue
                from scipy.stats import wilcoxon

                p_value = 1.0 if np.allclose(left, right) else float(wilcoxon(left, right).pvalue)
                records.append({
                    "method_id": method,
                    "baseline_id": baseline,
                    "dataset_id": cell[0],
                    "partition": cell[1],
                    "budget": cell[2],
                    "metric": metric,
                    "paired_seeds": len(seeds),
                    "median_method": float(np.median(left)),
                    "median_baseline": float(np.median(right)),
                    "wilcoxon_p_value": p_value,
                })
                p_values.append(p_value)
    for record, adjusted in zip(records, holm_adjust(p_values), strict=True):
        record["holm_adjusted_p_value"] = float(adjusted)
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--game-root", type=Path, default=Path("outputs/pg_elr_paper/confirmatory/games"))
    parser.add_argument("--output-root", type=Path, default=Path("outputs/pg_elr_paper/confirmatory"))
    parser.add_argument("--official-repo", type=Path, default=Path("external/svarm_official"))
    parser.add_argument("--pydvl-python", type=Path, default=Path("../.venv-pydvl/bin/python3"))
    parser.add_argument("--flush-every", type=int, default=25)
    parser.add_argument("--seed-start", type=int, default=0)
    parser.add_argument("--seed-stop", type=int, default=100)
    parser.add_argument("--raw-only", action="store_true")
    args = parser.parse_args()
    if not 0 <= args.seed_start < args.seed_stop <= 100:
        raise ValueError("seed shard must satisfy 0 <= start < stop <= 100")

    freeze = BENCHMARK / "evidence/pg_elr/confirmatory_protocol_freeze.json"
    authorization = authorize_pg_elr_confirmatory(
        freeze, expected_source_hashes=_source_hashes()
    )
    protocol = authorization.payload
    games = load_real_development_games(args.game_root)
    if {item.dataset_id for item in games} != {"fashion_mnist", "cifar10_subset"}:
        raise RuntimeError("confirmatory game set is incomplete or contaminated")
    expected_hashes = {
        json.loads(path.read_text())["dataset_id"]: json.loads(path.read_text())["feature_hash"]
        for path in args.game_root.glob("*_summary.json")
    }
    if set(expected_hashes) != {"fashion_mnist", "cifar10_subset"}:
        raise RuntimeError("confirmatory feature manifests are incomplete")

    methods = tuple(protocol["methods"])
    execution_methods = tuple(method for method in methods if method != "bd_pg_elr")
    selected = protocol["selection"]
    config = BudgetDebitedConfig(
        int(selected["probe_players"]),
        tuple(range(int(selected["calibration_seeds"]))),
        int(selected["calibration_budget"]),
    )
    raw_path = args.output_root / "raw_results.jsonl"
    existing = read_result_rows(raw_path)
    completed_ids = {str(row["run_id"]) for row in existing}
    batch = []
    added = 0
    for game in games:
        budgets = protocol["budgets"][f"n{len(game.game.high.owner_ids)}"]
        for row in iter_development_rows(
            (game,),
            budgets=budgets,
            seeds=range(args.seed_start, args.seed_stop),
            direct_methods=execution_methods,
            configs=(config,),
            completed_run_ids=completed_ids,
            official_repo=args.official_repo,
            pydvl_python=args.pydvl_python,
        ):
            batch.append(row)
            if len(batch) >= args.flush_every:
                added += append_result_rows(raw_path, batch)
                batch.clear()
    added += append_result_rows(raw_path, batch)
    rows = read_result_rows(raw_path)
    current = [row for row in rows if row["method_id"] in set(methods)]
    if args.raw_only:
        print(json.dumps({
            "seed_start": args.seed_start,
            "seed_stop": args.seed_stop,
            "observed_rows": len(current),
            "new_rows": added,
            "raw_results_sha256": _sha256(raw_path),
        }, sort_keys=True))
        return
    expected_rows = sum(
        len(protocol["budgets"][f"n{len(game.game.high.owner_ids)}"]) * 100 * len(methods)
        for game in games
    )
    baselines = _baseline_by_cell(current)
    strict_rows, _ = selection_rows(current, direct_methods=ALL_DIRECT_METHODS)
    analysis = {
        "schema_version": "1.0",
        "protocol_hash": authorization.protocol_hash,
        "expected_rows": expected_rows,
        "observed_rows": len(current),
        "completed_rows": sum(row["status"] == "completed" for row in current),
        "failed_rows": sum(row["status"] == "failed" for row in current),
        "skipped_rows": sum(row["status"] == "skipped" for row in current),
        "strict_cost_violations": sum(
            row["status"] == "completed"
            and float(row["realized_equivalent_cost"]) > float(row["budget"]) + 1e-9
            for row in current
        ),
        "strongest_direct_method_by_cell": {"|".join(map(str, key)): value for key, value in baselines.items()},
        "strict_selected_rows": strict_rows,
        "method_comparisons": _comparisons(current, baselines),
        "downstream_comparisons": _downstream(current, baselines),
        "amortized_original": amortized_envelope_summary(current, direct_methods=ALL_DIRECT_METHODS, method_id="pg_elr"),
        "amortized_adaptive": amortized_envelope_summary(current, direct_methods=ALL_DIRECT_METHODS, method_id="pg_elr_adaptive_direct"),
    }
    _atomic_json(args.output_root / "analysis.json", analysis)
    manifest = {
        "schema_version": "1.0",
        "phase": "confirmatory",
        "protocol_hash": authorization.protocol_hash,
        "physical_gpus": sorted({json.loads(path.read_text())["physical_gpu"] for path in args.game_root.glob("*_summary.json")}),
        "gpu_zero_visible": False,
        "games": [item.game.setting_id for item in games],
        "game_hashes": [item.game.high.content_hash for item in games],
        "feature_hashes": expected_hashes,
        "methods": list(methods),
        "expected_rows": expected_rows,
        "observed_rows": len(current),
        "new_rows": added,
        "complete": len(current) == expected_rows,
        "raw_results_sha256": _sha256(raw_path),
        "analysis_sha256": _sha256(args.output_root / "analysis.json"),
    }
    _atomic_json(args.output_root / "study_manifest.json", manifest)
    print(json.dumps(manifest, sort_keys=True))


if __name__ == "__main__":
    main()
