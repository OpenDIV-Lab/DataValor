"""Resume-safe development experiments over real cached coalition games."""

from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

import numpy as np
from scipy.stats import wilcoxon

from .coalition_games import CoalitionGameTable
from .elr_market import build_owner_costs, evaluate_market_consequences
from .elr_statistics import score_vector_metrics
from .elr_study import DEFAULT_SCR_CONFIG, StudyGame, _run_method
from .methods.valuation_multifidelity import (
    BudgetDebitedConfig,
    InapplicableBudgetError,
    select_budget_debited_method,
)
from .methods.valuation_shapley import OptionalMethodUnavailable
from .methods.valuation_slope_calibrated import SlopeCalibratedConfig
from .methods.valuation_slope_calibrated_plus import run_slope_calibrated_svarm_plus
from .methods.valuation_sota import evaluate_sota
from .statistics import geometric_mean, holm_adjust

DIRECT_METHODS = (
    "shapiq_svarm",
    "shapiq_stratified_sampling",
    "shapiq_kernel_shap",
    "shapiq_unbiased_kernel_shap",
    "shapiq_owen",
    "shapiq_leverage_shap",
    "shapley_mc",
    "tmc_shapley",
    "owen_shapley",
    "shapley_antithetic",
    "shapley_stratified",
)


@dataclass(frozen=True)
class RealDevelopmentGame:
    dataset_id: str
    partition: str
    ratios: Mapping[str, float]
    source_input_hash: str
    source_content_hash: str
    summary_path: str
    game: StudyGame
    owner_row_counts: Mapping[str, int] | None = None


@dataclass(frozen=True)
class RealBuildSpec:
    feature_kind: str
    model_family: str
    cap: int | None
    transform_id: str
    schema_id: str = "none"


def real_build_spec(dataset_id: str) -> RealBuildSpec:
    specs = {
        "breast_cancer": RealBuildSpec(
            "tabular_numeric", "tree_ensemble", None, "tabular-identity-v1"
        ),
        "wine": RealBuildSpec(
            "tabular_numeric", "tree_ensemble", None, "tabular-identity-v1"
        ),
        "adult": RealBuildSpec(
            "mixed_tabular_hashing",
            "boosting",
            6000,
            "adult-public-hashing-v1",
            "adult-openml-1590-v1",
        ),
        "digits": RealBuildSpec(
            "tabular_numeric", "neural_head", None, "digits-pixels-identity-v1"
        ),
        "ag_news": RealBuildSpec(
            "text_hashing", "neural_head", 6000, "text-hashing-2048-v1"
        ),
        "20newsgroups": RealBuildSpec(
            "text_hashing", "neural_head", 6000, "text-hashing-2048-v1"
        ),
        "fashion_mnist": RealBuildSpec(
            "resnet18_frozen", "neural_head", 6000, "resnet18-default-v1"
        ),
        "cifar10_subset": RealBuildSpec(
            "resnet18_frozen", "neural_head", 6000, "resnet18-default-v1"
        ),
    }
    try:
        return specs[dataset_id]
    except KeyError as exc:
        raise ValueError(f"unsupported real dataset: {dataset_id}") from exc


_DATASET_METADATA = {
    "breast": ("breast_cancer", "tabular", "tree_ensemble", "ensemble_width"),
    "wine": ("wine", "tabular", "tree_ensemble", "ensemble_width"),
    "california": ("california_housing", "tabular", "boosting", "boosting_round_prefix"),
    "diabetes": ("diabetes", "tabular", "boosting", "boosting_round_prefix"),
    "digits": ("digits", "image", "neural_head", "training_epoch_prefix"),
    "adult": ("adult", "mixed_tabular", "boosting", "boosting_round_prefix"),
    "agnews": ("ag_news", "text", "neural_head", "training_epoch_prefix"),
    "20news": ("20_newsgroups", "text", "neural_head", "training_epoch_prefix"),
    "fashion": ("fashion_mnist", "image", "neural_head", "training_epoch_prefix"),
    "cifar": ("cifar10_subset", "image", "neural_head", "training_epoch_prefix"),
}


def _dataset_metadata(setting_id: str) -> tuple[str, str, str, str]:
    for token, metadata in _DATASET_METADATA.items():
        if f"-{token}-" in setting_id:
            return metadata
    raise ValueError(f"unrecognized real development setting: {setting_id}")


def _partition(summary: Mapping[str, Any], setting_id: str) -> str:
    if summary.get("partition"):
        return str(summary["partition"])
    for name in ("quantity_skew", "label_skew", "iid"):
        if f"-{name}-" in setting_id:
            return name
    raise ValueError(f"cannot infer partition from {setting_id}")


def _cost_records(root: Path) -> dict[str, Mapping[str, Any]]:
    records: dict[str, Mapping[str, Any]] = {}
    for path in sorted(root.glob("measured_costs_*.json")):
        payload = json.loads(path.read_text())
        for dataset_id, record in payload.items():
            records[str(dataset_id)] = record
    return records


def _completed_games(root: Path) -> tuple[tuple[Path, Mapping[str, Any]], ...]:
    completed = []
    markers = {
        *sorted((root / "games").glob("*/.complete.json")),
        *sorted((root / "cache").glob("*/.complete.json")),
    }
    for marker in sorted(markers):
        payload = json.loads(marker.read_text())
        if int(payload.get("coalitions", 0)) <= 0:
            continue
        completed.append((marker.parent, payload))
    return tuple(completed)


def _resolve_game_dir(
    summary: Mapping[str, Any],
    completed: Sequence[tuple[Path, Mapping[str, Any]]],
) -> tuple[Path, Mapping[str, Any]]:
    input_hash = summary.get("input_hash")
    tables_hash = summary.get("tables_hash")
    for path, marker in completed:
        if input_hash and marker.get("input_hash") == input_hash:
            return path, marker
        if tables_hash and marker.get("content_hash") == tables_hash:
            return path, marker
    identifier = input_hash or tables_hash or "missing identifier"
    raise ValueError(f"no completed coalition game for {identifier}")


def load_real_development_games(cache_root: str | Path) -> tuple[RealDevelopmentGame, ...]:
    """Load complete n-owner high/medium games referenced by real summaries."""

    root = Path(cache_root)
    costs = _cost_records(root)
    completed = _completed_games(root)
    loaded: list[RealDevelopmentGame] = []
    for summary_path in sorted(root.glob("*_summary.json")):
        if summary_path.name == "pg_elr_dual_probe_summary.json":
            continue
        summary = json.loads(summary_path.read_text())
        setting_id = str(summary.get("setting_id", ""))
        if not setting_id:
            continue
        dataset_id, modality, model_family, mechanism = _dataset_metadata(setting_id)
        game_dir, marker = _resolve_game_dir(summary, completed)
        coalition_paths = sorted((game_dir / "coalitions").glob("*.json"))
        expected = int(marker["coalitions"])
        if len(coalition_paths) != expected or expected & (expected - 1):
            raise ValueError(f"incomplete or non-power-of-two game: {game_dir}")
        values = {"low": {}, "medium": {}, "high": {}}
        for coalition_path in coalition_paths:
            payload = json.loads(coalition_path.read_text())
            mask = int(payload["mask"])
            for fidelity in values:
                values[fidelity][mask] = float(payload["utilities"][fidelity])
        n_players = expected.bit_length() - 1
        owner_ids = tuple(f"owner-{index}" for index in range(n_players))
        source_metadata = {
            "input_hash": marker["input_hash"],
            "content_hash": marker["content_hash"],
            "table_hashes": marker.get("table_hashes", {}),
        }
        high = CoalitionGameTable(owner_ids, values["high"], "high", metadata=source_metadata)
        medium = CoalitionGameTable(
            owner_ids,
            values["medium"],
            "medium",
            metadata=source_metadata,
        )
        ratio_record = costs.get(dataset_id)
        if not ratio_record:
            raise ValueError(f"missing measured cost ratios for {dataset_id}")
        ratios = {
            "q1": float(ratio_record["ratio_q1"]),
            "median": float(ratio_record["ratio_median"]),
            "q3": float(ratio_record["ratio_q3"]),
        }
        loaded.append(
            RealDevelopmentGame(
                dataset_id,
                _partition(summary, setting_id),
                ratios,
                str(marker["input_hash"]),
                str(marker["content_hash"]),
                str(summary_path),
                StudyGame(
                    setting_id,
                    modality,
                    model_family,
                    mechanism,
                    high,
                    medium,
                    evidence_scope="real_trained_game",
                ),
                {
                    str(owner): int(count)
                    for owner, count in summary.get("owner_row_counts", {}).items()
                }
                or None,
            )
        )
    if not loaded:
        raise ValueError(f"no completed real development games under {root}")
    return tuple(sorted(loaded, key=lambda item: (item.dataset_id, item.partition)))


def candidate_grid(
    *,
    owner_count: int = 8,
    reference_budget: int = 224,
) -> tuple[BudgetDebitedConfig, ...]:
    candidates = []
    for probe_players in (4, 5, 6):
        calibration_budget = math.floor(
            reference_budget / (2 ** (owner_count - probe_players))
        )
        calibration_budget = min(calibration_budget, (1 << probe_players) - 1)
        for seed_count in (10, 20, 40):
            candidates.append(
                BudgetDebitedConfig(
                    probe_players,
                    tuple(range(seed_count)),
                    calibration_budget,
                )
            )
    return tuple(candidates)


def _config_payload(config: BudgetDebitedConfig | None) -> Mapping[str, Any] | None:
    if config is None:
        return None
    return asdict(config)


def make_run_id(
    game_hash: str,
    budget: int,
    seed: int,
    method_id: str,
    config: BudgetDebitedConfig | None = None,
    *,
    ratio_kind: str = "median",
    scr_config: SlopeCalibratedConfig | None = None,
    scr_accounting: str = "cached",
) -> str:
    payload = {
        "game_hash": game_hash,
        "budget": int(budget),
        "seed": int(seed),
        "method_id": method_id,
        "config": _config_payload(config),
        "ratio_kind": ratio_kind,
    }
    if scr_config is not None:
        payload["scr_config"] = asdict(scr_config)
        payload["scr_accounting"] = scr_accounting
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:24]


def _evaluate_one(
    item: RealDevelopmentGame,
    *,
    budget: int,
    seed: int,
    method_id: str,
    config: BudgetDebitedConfig | None,
    ratio_kind: str,
    official_repo: Path | None = None,
    pydvl_python: Path | None = None,
    scr_config: SlopeCalibratedConfig | None = None,
    scr_accounting: str = "cached",
) -> dict[str, Any]:
    ratio = float(item.ratios[ratio_kind])
    effective_scr_config = (
        scr_config or DEFAULT_SCR_CONFIG if method_id.startswith("scr_") else None
    )
    run_id = make_run_id(
        item.game.high.content_hash,
        budget,
        seed,
        method_id,
        config,
        ratio_kind=ratio_kind,
        scr_config=effective_scr_config,
        scr_accounting=scr_accounting,
    )
    truth = evaluate_sota(
        "exact_table",
        item.game.high,
        budget=len(item.game.high.values),
        seed=0,
    )
    exact = np.asarray([truth.scores[owner] for owner in item.game.high.owner_ids])
    status = "completed"
    error = None
    diagnostics: dict[str, Any] = {}
    score_mae = None
    max_score_error = None
    scores = None
    score_metrics = None
    market_metrics = None
    started = time.perf_counter()
    try:
        if config is not None:
            output = select_budget_debited_method(
                item.game,
                budget=budget,
                config=config,
                low_cost_ratio=ratio,
                seed=seed,
            )
        elif method_id in {"scr_plus_beta_zero", "scr_plus_beta_one", "scr_plus"}:
            if official_repo is None:
                raise OptionalMethodUnavailable("official_repository_path_missing:svarm")
            beta_mode = {
                "scr_plus_beta_zero": "zero",
                "scr_plus_beta_one": "one",
                "scr_plus": "learned",
            }[method_id]
            output = run_slope_calibrated_svarm_plus(
                item.game.high,
                item.game.low,
                budget=budget,
                seed=seed,
                config=effective_scr_config or DEFAULT_SCR_CONFIG,
                official_repo=official_repo,
                beta_mode=beta_mode,
            )
        elif method_id in {
            "official_stratified_svarm",
            "official_stratified_svarm_plus",
            "pydvl_vrds",
            "pydvl_owen",
            "pydvl_group_testing",
        }:
            output = evaluate_sota(
                method_id,
                item.game.high,
                budget=budget,
                seed=seed,
                official_repo=official_repo,
                pydvl_python=pydvl_python,
            )
        else:
            output = _run_method(
                method_id,
                item.game,
                budget,
                seed,
                ratio,
                official_repo=None,
                scr_config=effective_scr_config or DEFAULT_SCR_CONFIG,
                scr_accounting=scr_accounting,
            )
        predicted = np.asarray(
            [output.scores[owner] for owner in item.game.high.owner_ids]
        )
        score_metrics = score_vector_metrics(predicted, exact)
        score_mae = score_metrics["mae"]
        max_score_error = score_metrics["max_owner_error"]
        scores = {
            owner: float(output.scores[owner]) for owner in item.game.high.owner_ids
        }
        if item.owner_row_counts is not None:
            exact_scores = {
                owner: float(exact[index])
                for index, owner in enumerate(item.game.high.owner_ids)
            }
            owner_costs = build_owner_costs(item.owner_row_counts, unit_cost=1.0)
            market_metrics = asdict(
                evaluate_market_consequences(
                    item.game.high, scores, exact_scores, owner_costs
                )
            )
        diagnostics = dict(output.diagnostics)
    except InapplicableBudgetError as exc:
        status = "skipped"
        error = f"inapplicable_budget:{exc.reason}"
        diagnostics = dict(exc.diagnostics)
    except OptionalMethodUnavailable as exc:
        status = "skipped"
        error = exc.reason
    except ValueError as exc:
        message = str(exc)
        if "budget" in message or "equivalent cost" in message:
            status = "skipped"
            error = f"inapplicable_budget:{message}"
        else:
            status = "failed"
            error = f"ValueError:{message}"
    except Exception as exc:  # Preserve all failures in the append-only ledger.
        status = "failed"
        error = f"{type(exc).__name__}:{exc}"
    elapsed = time.perf_counter() - started
    realized = diagnostics.get(
        "realized_equivalent_cost",
        diagnostics.get("equivalent_high_calls", diagnostics.get("logical_calls", budget)),
    )
    return {
        "schema_version": "1.0",
        "run_id": run_id,
        "dataset_id": item.dataset_id,
        "partition": item.partition,
        "setting_id": item.game.setting_id,
        "game_hash": item.game.high.content_hash,
        "medium_game_hash": item.game.low.content_hash,
        "source_input_hash": item.source_input_hash,
        "source_content_hash": item.source_content_hash,
        "owner_count": len(item.game.high.owner_ids),
        "budget": int(budget),
        "seed": int(seed),
        "method_id": method_id,
        "probe_players": config.probe_players if config else None,
        "calibration_seed_count": len(config.calibration_seeds) if config else None,
        "calibration_budget": config.calibration_budget if config else None,
        "ratio_kind": ratio_kind,
        "low_cost_ratio": ratio,
        "status": status,
        "error": error,
        "score_mae": score_mae,
        "max_score_error": max_score_error,
        "scores": scores,
        "score_metrics": score_metrics,
        "market_metrics": market_metrics,
        "realized_equivalent_cost": float(realized),
        "runtime_seconds": elapsed,
        "diagnostics": diagnostics,
        "scr_config": asdict(effective_scr_config) if effective_scr_config else None,
        "scr_accounting": scr_accounting if method_id.startswith("scr_") else None,
    }


def iter_development_rows(
    games: Iterable[RealDevelopmentGame],
    *,
    budgets: Iterable[int],
    seeds: Iterable[int],
    direct_methods: Sequence[str] = DIRECT_METHODS,
    configs: Sequence[BudgetDebitedConfig] | None = None,
    ratio_kind: str = "median",
    completed_run_ids: Iterable[str] = (),
    official_repo: Path | None = None,
    pydvl_python: Path | None = None,
    scr_config: SlopeCalibratedConfig | None = None,
    scr_accounting: str = "cached",
) -> Iterator[dict[str, Any]]:
    """Yield only missing direct and BD-PG-ELR runs in deterministic order."""

    seen = set(completed_run_ids)
    materialized_configs = tuple(candidate_grid() if configs is None else configs)
    for item in games:
        for budget in budgets:
            for seed in seeds:
                for method_id in direct_methods:
                    run_id = make_run_id(
                        item.game.high.content_hash,
                        budget,
                        seed,
                        method_id,
                        ratio_kind=ratio_kind,
                        scr_config=scr_config if method_id.startswith("scr_") else None,
                        scr_accounting=scr_accounting,
                    )
                    if run_id not in seen:
                        yield _evaluate_one(
                            item,
                            budget=int(budget),
                            seed=int(seed),
                            method_id=method_id,
                            config=None,
                            ratio_kind=ratio_kind,
                            official_repo=official_repo,
                            pydvl_python=pydvl_python,
                            scr_config=scr_config,
                            scr_accounting=scr_accounting,
                        )
                for config in materialized_configs:
                    run_id = make_run_id(
                        item.game.high.content_hash,
                        budget,
                        seed,
                        "bd_pg_elr",
                        config,
                        ratio_kind=ratio_kind,
                    )
                    if run_id not in seen:
                        yield _evaluate_one(
                            item,
                            budget=int(budget),
                            seed=int(seed),
                            method_id="bd_pg_elr",
                            config=config,
                            ratio_kind=ratio_kind,
                            official_repo=official_repo,
                            pydvl_python=pydvl_python,
                        )


def selection_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    direct_methods: Sequence[str] = DIRECT_METHODS,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Pair each BD row with the strongest median direct estimator per cell."""

    materialized = [dict(row) for row in rows]
    direct = set(direct_methods)
    grouped: dict[tuple[str, int, str], list[float]] = {}
    for row in materialized:
        if row.get("method_id") not in direct or row.get("status") != "completed":
            continue
        key = (str(row["game_hash"]), int(row["budget"]), str(row["method_id"]))
        grouped.setdefault(key, []).append(float(row["score_mae"]))
    chosen: dict[tuple[str, int], str] = {}
    for game_hash, budget, method_id in sorted(grouped):
        key = (game_hash, budget)
        candidate = (statistics.median(grouped[(game_hash, budget, method_id)]), method_id)
        incumbent_method = chosen.get(key)
        if incumbent_method is None:
            chosen[key] = method_id
        else:
            incumbent = (
                statistics.median(grouped[(game_hash, budget, incumbent_method)]),
                incumbent_method,
            )
            if candidate < incumbent:
                chosen[key] = method_id
    paired = {
        (str(row["game_hash"]), int(row["budget"]), int(row["seed"]), str(row["method_id"])): row
        for row in materialized
        if row.get("status") == "completed"
    }
    selected: list[dict[str, Any]] = []
    for row in materialized:
        if row.get("method_id") != "bd_pg_elr":
            continue
        cell = (str(row["game_hash"]), int(row["budget"]))
        baseline_method = chosen.get(cell)
        baseline = paired.get((*cell, int(row["seed"]), baseline_method)) if baseline_method else None
        diagnostics = row.get("diagnostics") or {}
        selected.append(
            {
                "dataset_id": row["dataset_id"],
                "partition": row["partition"],
                "budget": row["budget"],
                "seed": row["seed"],
                "owner_count": row["owner_count"],
                "probe_players": row["probe_players"],
                "calibration_seed_count": row["calibration_seed_count"],
                "status": "completed"
                if row.get("status") == "completed" and baseline is not None
                else "failed",
                "method_mae": row.get("score_mae"),
                "baseline_mae": baseline.get("score_mae") if baseline else None,
                "baseline_method": baseline_method,
                "routing_inputs": {
                    "probe_median_mae": diagnostics.get("probe_median_mae", ()),
                    "probe_winners": diagnostics.get("probe_winners", ()),
                    "budget": row["budget"],
                    "low_cost_ratio": row["low_cost_ratio"],
                    "probe_players": row["probe_players"],
                    "calibration_seed_count": row["calibration_seed_count"],
                },
            }
        )
    printable = {f"{game_hash}|{budget}": method for (game_hash, budget), method in chosen.items()}
    return selected, printable


def amortized_envelope_summary(
    rows: Iterable[Mapping[str, Any]],
    *,
    direct_methods: Sequence[str] = DIRECT_METHODS,
    method_id: str = "pg_elr_adaptive_direct",
    tie_tolerance: float = 0.01,
) -> dict[str, Any]:
    """Compare amortized PG-ELR to the strongest direct method in each cell."""

    materialized = [
        dict(row)
        for row in rows
        if row.get("status") == "completed"
        and row.get("method_id") in {*direct_methods, method_id}
    ]
    grouped: dict[tuple[str, int, str], list[dict[str, Any]]] = {}
    for row in materialized:
        grouped.setdefault(
            (str(row["game_hash"]), int(row["budget"]), str(row["method_id"])),
            [],
        ).append(row)
    cells = sorted({(key[0], key[1]) for key in grouped})
    comparisons = []
    p_values = []
    for game_hash, budget in cells:
        pg_rows = grouped.get((game_hash, budget, method_id), [])
        available = [
            method
            for method in direct_methods
            if grouped.get((game_hash, budget, method))
        ]
        if not pg_rows or not available:
            continue
        baseline_method = min(
            available,
            key=lambda method: (
                statistics.median(
                    float(row["score_mae"])
                    for row in grouped[(game_hash, budget, method)]
                ),
                direct_methods.index(method),
            ),
        )
        pg_by_seed = {int(row["seed"]): float(row["score_mae"]) for row in pg_rows}
        baseline_by_seed = {
            int(row["seed"]): float(row["score_mae"])
            for row in grouped[(game_hash, budget, baseline_method)]
        }
        seeds = sorted(set(pg_by_seed) & set(baseline_by_seed))
        pg_values = np.asarray([pg_by_seed[seed] for seed in seeds])
        baseline_values = np.asarray([baseline_by_seed[seed] for seed in seeds])
        pg_median = float(np.median(pg_values))
        baseline_median = float(np.median(baseline_values))
        ratio = pg_median / baseline_median if baseline_median > 0 else 1.0
        if np.allclose(pg_values, baseline_values, rtol=0.0, atol=1e-15):
            p_value = 1.0
        else:
            p_value = float(wilcoxon(pg_values, baseline_values, alternative="less").pvalue)
        first = pg_rows[0]
        comparisons.append(
            {
                "dataset_id": first["dataset_id"],
                "partition": first["partition"],
                "budget": budget,
                "paired_seeds": len(seeds),
                "baseline_method": baseline_method,
                "pg_elr_median_mae": pg_median,
                "baseline_median_mae": baseline_median,
                "mae_ratio": ratio,
                "outcome": "win"
                if ratio < 1.0 - tie_tolerance
                else "loss"
                if ratio > 1.0 + tie_tolerance
                else "tie",
                "wilcoxon_less_p_value": p_value,
            }
        )
        p_values.append(p_value)
    adjusted = holm_adjust(p_values)
    for cell, value in zip(comparisons, adjusted, strict=True):
        cell["holm_adjusted_p_value"] = float(value)
    comparisons.sort(key=lambda cell: (cell["dataset_id"], cell["partition"], cell["budget"]))
    ratios = [float(cell["mae_ratio"]) for cell in comparisons]
    return {
        "cell_count": len(comparisons),
        "wins": sum(cell["outcome"] == "win" for cell in comparisons),
        "ties": sum(cell["outcome"] == "tie" for cell in comparisons),
        "losses": sum(cell["outcome"] == "loss" for cell in comparisons),
        "geometric_mean_mae_ratio": geometric_mean(ratios),
        "holm_significant_wins": sum(
            cell["outcome"] == "win" and cell["holm_adjusted_p_value"] < 0.05
            for cell in comparisons
        ),
        "cells": comparisons,
    }


def read_result_rows(path: str | Path) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    rows = []
    seen = set()
    for line_number, line in enumerate(target.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"corrupt result row at line {line_number}") from exc
        run_id = str(row.get("run_id", ""))
        if not run_id or run_id in seen:
            raise ValueError(f"missing or duplicate run_id at line {line_number}")
        seen.add(run_id)
        rows.append(row)
    return rows


def append_result_rows(path: str | Path, rows: Iterable[Mapping[str, Any]]) -> int:
    """Append each new run once and durably flush resumable evidence."""

    target = Path(path)
    existing = read_result_rows(target)
    seen = {str(row["run_id"]) for row in existing}
    additions = []
    for raw in rows:
        row = dict(raw)
        run_id = str(row.get("run_id", ""))
        if not run_id:
            raise ValueError("result row requires a non-empty run_id")
        if run_id not in seen:
            seen.add(run_id)
            additions.append(row)
    if additions:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as stream:
            for row in additions:
                stream.write(json.dumps(row, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    return len(additions)


__all__ = [
    "DIRECT_METHODS",
    "RealDevelopmentGame",
    "RealBuildSpec",
    "amortized_envelope_summary",
    "append_result_rows",
    "candidate_grid",
    "iter_development_rows",
    "load_real_development_games",
    "make_run_id",
    "read_result_rows",
    "real_build_spec",
    "selection_rows",
]
