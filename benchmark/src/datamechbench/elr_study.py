"""Run cost-matched Shapley estimators on immutable cached coalition games."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Mapping

import numpy as np

from .coalition_games import CoalitionGameTable
from .methods.valuation_multifidelity import (
    BudgetDebitedConfig,
    InapplicableBudgetError,
    ProbeRisk,
    build_probe_games,
    complementary_probe_plan,
    make_budget_ledger,
    resolve_probe_risks,
    run_exact_low_residual,
    select_budget_debited_method,
)
from .methods.valuation_shapley import (
    OptionalMethodUnavailable,
    evaluate_shapley,
    native_shapley_parameters,
)
from .methods.valuation_slope_calibrated import (
    SlopeCalibratedConfig,
    run_slope_calibrated_residual,
)
from .methods.valuation_sota import evaluate_sota
from .metrics import MetricValue, evaluate_valuation_market_metrics
from .models import BenchmarkResult, ValuationCase, ValuationOutput
from .settings.valuation_mechanisms import ValuationMechanismSetting

DEFAULT_METHODS = (
    "scr_shapley",
    "scr_beta_zero",
    "scr_beta_one",
    "bd_pg_elr",
    "pg_elr",
    "pg_elr_adaptive_direct",
    "elr_residual_leverage",
    "shapley_exact_low_residual",
    "shapley_stratified",
    "shapley_mc",
    "tmc_shapley",
    "owen_shapley",
    "shapley_antithetic",
    "shapiq_svarm",
    "shapiq_stratified_sampling",
    "shapiq_kernel_shap",
    "shapiq_unbiased_kernel_shap",
    "shapiq_owen",
    "shapiq_leverage_shap",
    "official_stratified_svarm",
    "official_stratified_svarm_plus",
    "pydvl_vrds",
    "pydvl_owen",
    "pydvl_group_testing",
    "asss_a",
    "asss_b",
)


@dataclass(frozen=True)
class PaperComparator:
    method_id: str
    category: str
    source: str
    version: str
    minimum_budget: str
    implementation_kind: str = "project_native"
    unavailable_policy: str = "not_applicable"
    estimand: str = "ordinary_group_data_shapley"


PAPER_COMPARATORS = (
    *(PaperComparator(name, "direct_high_fidelity", "shapiq", "1.7.0", "2") for name in (
        "shapiq_svarm",
        "shapiq_stratified_sampling",
        "shapiq_kernel_shap",
        "shapiq_unbiased_kernel_shap",
        "shapiq_owen",
        "shapiq_leverage_shap",
    )),
    *(PaperComparator(name, "direct_high_fidelity", "DataValor", "source_hash", rule) for name, rule in (
        ("shapley_mc", "n+1"),
        ("tmc_shapley", "n+2"),
        ("owen_shapley", "2n"),
        ("shapley_antithetic", "n+1"),
        ("shapley_stratified", "2n^2"),
    )),
    PaperComparator("elr_residual_leverage", "ungated_multifidelity", "DataValor", "source_hash", "2^n*c_M+2"),
    PaperComparator("pg_elr", "amortized_routed_multifidelity", "DataValor", "source_hash", "production budget; probe amortized"),
    PaperComparator("pg_elr_adaptive_direct", "amortized_routed_multifidelity", "DataValor", "source_hash", "production budget; adaptive direct fallback; probe amortized"),
    PaperComparator("bd_pg_elr", "one_shot_routed_multifidelity", "DataValor", "source_hash", "probe+production shared budget"),
    PaperComparator(
        "scr_shapley",
        "slope_calibrated_multifidelity",
        "DataValor",
        "source_hash",
        "cached: n+1; strict: 2^n*c_M+n+1",
    ),
    PaperComparator(
        "scr_beta_zero",
        "matched_direct_ablation",
        "DataValor",
        "source_hash",
        "cached: n+1; strict: 2^n*c_M+n+1",
    ),
    PaperComparator(
        "scr_beta_one",
        "fixed_slope_multifidelity_ablation",
        "DataValor",
        "source_hash",
        "cached: n+1; strict: 2^n*c_M+n+1",
    ),
    *(PaperComparator(name, "direct_high_fidelity", source, version, minimum, "official_external", "structured_na") for name, source, version, minimum in (
        ("official_stratified_svarm", "S-SVARM official repository", "c4e30395", "2n+1"),
        ("official_stratified_svarm_plus", "S-SVARM official repository", "c4e30395", "2n+1"),
        ("pydvl_vrds", "pyDVL", "0.10.0", "2"),
        ("pydvl_owen", "pyDVL", "0.10.0", "2"),
        ("pydvl_group_testing", "pyDVL", "0.10.0", "2"),
    )),
)

DEFAULT_BUDGET_DEBITED_CONFIG = BudgetDebitedConfig(
    probe_players=6,
    calibration_seeds=tuple(range(40)),
    calibration_budget=56,
)

DEFAULT_SCR_CONFIG = SlopeCalibratedConfig(ridge_relative=0.1)
SCR_METHOD_MODES = {
    "scr_shapley": "learned",
    "scr_beta_zero": "zero",
    "scr_beta_one": "one",
}


@dataclass(frozen=True)
class StudyGame:
    setting_id: str
    modality: str
    model_family: str
    fidelity_mechanism: str
    high: CoalitionGameTable
    low: CoalitionGameTable
    evidence_scope: str = "controlled_cached_game"


@dataclass(frozen=True)
class ProbeSelection:
    selected_method: str
    median_probe_mae: dict[str, float]
    probe_winners: tuple[str, ...]
    probe_players: int
    calibration_budget: int
    calibration_high_calls: int
    calibration_seeds: int


_PROBE_SELECTION_CACHE: dict[tuple[object, ...], ProbeSelection] = {}


def resolve_probe_winners(probe_winners: Iterable[str]) -> str:
    winners = tuple(probe_winners)
    if not winners:
        raise ValueError("probe_winners must not be empty")
    return winners[0] if len(set(winners)) == 1 else "shapiq_svarm"


def resolve_amortized_disagreement(
    probe_winners: Iterable[str],
    aggregate_median_mae: Mapping[str, float],
) -> str:
    """Keep unanimous routing; otherwise choose the safer direct probe winner."""

    winners = tuple(probe_winners)
    if not winners:
        raise ValueError("probe_winners must not be empty")
    if len(set(winners)) == 1:
        return winners[0]
    direct = ("shapiq_svarm", "shapiq_leverage_shap")
    missing = [method for method in direct if method not in aggregate_median_mae]
    if missing:
        raise ValueError(f"missing direct fallback risks: {missing}")
    return min(
        direct,
        key=lambda method: (float(aggregate_median_mae[method]), direct.index(method)),
    )


def _truth(table: CoalitionGameTable) -> ValuationOutput:
    return evaluate_sota("exact_table", table, budget=len(table.values), seed=0)


def _residual_efficiency(game: StudyGame) -> float:
    high_marginals = []
    residual_marginals = []
    for player in range(len(game.high.owner_ids)):
        bit = 1 << player
        for mask in range(1 << len(game.high.owner_ids)):
            if mask & bit:
                continue
            high = game.high.values[mask | bit] - game.high.values[mask]
            low = game.low.values[mask | bit] - game.low.values[mask]
            high_marginals.append(high)
            residual_marginals.append(high - low)
    denominator = float(np.var(high_marginals))
    return float(np.var(residual_marginals) / denominator) if denominator else 0.0


def _market_setting(game: StudyGame, index: int) -> ValuationMechanismSetting:
    owners = game.high.owner_ids
    mechanisms = (
        "top_k_acquisition",
        "budgeted_procurement",
        "revenue_allocation",
        "sequential_acquisition",
    )
    mechanism = mechanisms[index % len(mechanisms)]
    costs = {owner: Decimal(str(1 + position % 4)) for position, owner in enumerate(owners)}
    return ValuationMechanismSetting(
        setting_id=f"market-{game.setting_id}",
        mechanism=mechanism,
        owner_ids=owners,
        methods=(),
        costs=costs,
        budget=Decimal("12") if mechanism == "budgeted_procurement" else Decimal("100"),
        top_k=max(1, len(owners) // 3),
        target_utility=0.5,
    )


def _run_method(
    method_id: str,
    game: StudyGame,
    budget: int,
    seed: int,
    low_cost_ratio: float,
    *,
    official_repo: Path | None,
    scr_config: SlopeCalibratedConfig = DEFAULT_SCR_CONFIG,
    scr_accounting: str = "cached",
) -> ValuationOutput:
    if method_id in SCR_METHOD_MODES:
        return run_slope_calibrated_residual(
            game.high,
            game.low,
            budget=budget,
            seed=seed,
            config=scr_config,
            accounting=scr_accounting,
            low_cost_ratio=low_cost_ratio,
            beta_mode=SCR_METHOD_MODES[method_id],
        )
    if method_id == "bd_pg_elr":
        return select_budget_debited_method(
            game,
            budget=budget,
            config=DEFAULT_BUDGET_DEBITED_CONFIG,
            low_cost_ratio=low_cost_ratio,
            seed=seed,
        )
    if method_id in {"pg_elr", "pg_elr_adaptive_direct"}:
        adaptive_fallback = method_id == "pg_elr_adaptive_direct"
        selection = select_probe_gated_sampler(
            game,
            low_cost_ratio=low_cost_ratio,
            adaptive_direct_fallback=adaptive_fallback,
        )
        selected = _run_method(
            selection.selected_method,
            game,
            budget,
            seed,
            low_cost_ratio,
            official_repo=official_repo,
            scr_config=scr_config,
            scr_accounting=scr_accounting,
        )
        return ValuationOutput(
            selected.scores,
            diagnostics={
                **selected.diagnostics,
                "backend": "probe_gated_elr_adaptive_direct"
                if adaptive_fallback
                else "probe_gated_elr",
                "selected_method": selection.selected_method,
                "probe_median_mae": selection.median_probe_mae,
                "probe_winners": selection.probe_winners,
                "probe_players": selection.probe_players,
                "calibration_budget": selection.calibration_budget,
                "calibration_seeds": selection.calibration_seeds,
                "calibration_high_calls": selection.calibration_high_calls,
                "calibration_cost_accounting": "one_time_amortized",
                "disagreement_fallback": "best_average_direct"
                if adaptive_fallback
                else "shapiq_svarm",
            },
            utility_calls=selected.utility_calls,
        )
    if method_id in {"asss_a", "asss_b"}:
        raise OptionalMethodUnavailable("official_implementation_unavailable:asss")
    if method_id == "elr_residual_leverage":
        low_calls = len(game.low.values)
        residual_budget = int(budget - low_calls * low_cost_ratio)
        ledger = make_budget_ledger(
            declared_budget=budget,
            low_cost_ratio=low_cost_ratio,
            additional_medium_masks=game.low.values,
            additional_high_calls=max(0, residual_budget),
        )
        output = run_exact_low_residual(
            game.high,
            game.low,
            residual_method="shapiq_leverage_shap",
            residual_budget=residual_budget,
            seed=seed,
            ledger=ledger,
        )
        return ValuationOutput(
            output.scores,
            diagnostics={
                **output.diagnostics,
                "backend": "exact_low_plus_residual_leverage",
            },
            utility_calls=output.utility_calls,
        )
    if method_id == "shapley_exact_low_residual":
        case = ValuationCase(
            game.setting_id,
            game.high.owner_ids,
            game.high.value,
            "cached_coalition_game",
            metadata={"low_fidelity_game": game.low, "low_cost_ratio": low_cost_ratio},
        )
        return evaluate_shapley(
            method_id,
            case,
            {"equivalent_budget": budget, "low_cost_ratio": low_cost_ratio},
            seed,
        )
    if method_id == "shapley_stratified":
        case = ValuationCase(
            game.setting_id,
            game.high.owner_ids,
            game.high.value,
            "cached_coalition_game",
        )
        return evaluate_shapley(
            method_id, case, {"high_call_budget": budget}, seed
        )
    if method_id in {
        "shapley_mc",
        "tmc_shapley",
        "owen_shapley",
        "shapley_antithetic",
    }:
        case = ValuationCase(
            game.setting_id,
            game.high.owner_ids,
            game.high.value,
            "cached_coalition_game",
        )
        params = native_shapley_parameters(
            method_id,
            budget,
            len(game.high.owner_ids),
        )
        return evaluate_shapley(method_id, case, params, seed)
    return evaluate_sota(
        method_id,
        game.high,
        budget=budget,
        seed=seed,
        official_repo=official_repo,
    )


def select_probe_gated_sampler(
    game: StudyGame,
    *,
    low_cost_ratio: float,
    calibration_budget: int = 56,
    calibration_seeds: Iterable[int] = range(40),
    adaptive_direct_fallback: bool = False,
) -> ProbeSelection:
    """Select the sampler when two complementary six-owner probes agree.

    The union of probe coalitions is a one-time, setting-level calibration cost.
    A disagreement falls back to SVARM rather than forcing the residual method.
    Downstream reports must either amortize calibration across repeated valuations
    or show the one-shot accounting view separately.
    """
    seeds = tuple(int(seed) for seed in calibration_seeds)
    cache_key = (
        game.high.content_hash,
        game.low.content_hash,
        float(low_cost_ratio),
        int(calibration_budget),
        seeds,
        bool(adaptive_direct_fallback),
    )
    if cache_key in _PROBE_SELECTION_CACHE:
        return _PROBE_SELECTION_CACHE[cache_key]
    n_players = len(game.high.owner_ids)
    probe_players = 6
    if n_players < 8:
        raise ValueError("PG-ELR requires at least eight owners")
    if not seeds:
        raise ValueError("calibration_seeds must not be empty")
    candidates = (
        "elr_residual_leverage",
        "shapiq_svarm",
        "shapiq_leverage_shap",
    )
    plan = complementary_probe_plan(game.high.owner_ids, probe_players)
    probe_medians: list[dict[str, float]] = []
    probe_risks: list[ProbeRisk] = []
    for probe_index, probe in enumerate(build_probe_games(game, plan)):
        owner_ids = probe.high.owner_ids
        truth = _truth(probe.high)
        exact = np.asarray([truth.scores[owner] for owner in owner_ids])
        errors: dict[str, list[float]] = {candidate: [] for candidate in candidates}
        for candidate in candidates:
            for seed in seeds:
                output = _run_method(
                    candidate,
                    probe,
                    calibration_budget,
                    seed,
                    low_cost_ratio,
                    official_repo=None,
                )
                predicted = np.asarray([output.scores[owner] for owner in owner_ids])
                errors[candidate].append(float(np.mean(np.abs(predicted - exact))))
        medians = {name: float(np.median(values)) for name, values in errors.items()}
        probe_medians.append(medians)
        winner = min(candidates, key=lambda name: (medians[name], candidates.index(name)))
        probe_risks.append(
            ProbeRisk(probe_index=probe_index, median_mae=medians, winner=winner)
        )
    decision = resolve_probe_risks(probe_risks, fallback_method="shapiq_svarm")
    aggregate_medians = {
        candidate: float(np.mean([values[candidate] for values in probe_medians]))
        for candidate in candidates
    }
    selected_method = (
        resolve_amortized_disagreement(
            (risk.winner for risk in probe_risks),
            aggregate_medians,
        )
        if adaptive_direct_fallback
        else decision.selected_method
    )
    selection = ProbeSelection(
        selected_method,
        aggregate_medians,
        tuple(risk.winner for risk in probe_risks),
        probe_players,
        calibration_budget,
        len(plan.unique_high_masks),
        len(seeds),
    )
    _PROBE_SELECTION_CACHE[cache_key] = selection
    return selection


def run_cached_table_study(
    games: Iterable[StudyGame],
    *,
    budgets: Iterable[int],
    seeds: Iterable[int],
    method_ids: Iterable[str] = DEFAULT_METHODS,
    low_cost_ratio: float = 0.2,
    official_repo: Path | None = None,
    split: str = "development",
    scr_config: SlopeCalibratedConfig = DEFAULT_SCR_CONFIG,
    scr_accounting: str = "cached",
) -> tuple[BenchmarkResult, ...]:
    materialized_games = tuple(games)
    rows: list[BenchmarkResult] = []
    for game_index, game in enumerate(materialized_games):
        truth = _truth(game.high)
        market = _market_setting(game, game_index)
        residual_efficiency = _residual_efficiency(game)
        for budget in budgets:
            for seed in seeds:
                for method_id in method_ids:
                    key = f"{game.high.content_hash}|{budget}|{seed}|{method_id}"
                    run_id = hashlib.sha256(key.encode()).hexdigest()[:20]
                    started = time.perf_counter()
                    status = "completed"
                    error = None
                    metrics = {}
                    diagnostics = {}
                    try:
                        output = _run_method(
                            method_id,
                            game,
                            int(budget),
                            int(seed),
                            low_cost_ratio,
                            official_repo=official_repo,
                            scr_config=scr_config,
                            scr_accounting=scr_accounting,
                        )
                        predicted = np.asarray(
                            [output.scores[owner] for owner in game.high.owner_ids]
                        )
                        exact = np.asarray(
                            [truth.scores[owner] for owner in game.high.owner_ids]
                        )
                        metrics = dict(
                            evaluate_valuation_market_metrics(market, output, truth)
                        )
                        metrics["score_mae"] = MetricValue(
                            float(np.mean(np.abs(predicted - exact)))
                        )
                        metrics["max_score_error"] = MetricValue(
                            float(np.max(np.abs(predicted - exact)))
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
                        if "budget" in str(exc):
                            status = "skipped"
                            error = f"inapplicable_budget:{exc}"
                        else:
                            status = "failed"
                            error = str(exc)
                    except Exception as exc:  # Preserve failures in the raw ledger.
                        status = "failed"
                        error = f"{type(exc).__name__}:{exc}"
                    runtime = time.perf_counter() - started
                    equivalent_cost = diagnostics.get(
                        "equivalent_high_calls",
                        diagnostics.get("logical_calls", budget),
                    )
                    rows.append(
                        BenchmarkResult(
                            run_id,
                            "valuation",
                            method_id,
                            game.setting_id,
                            int(seed),
                            status,
                            metrics,
                            runtime,
                            error=error,
                            metadata={
                                "setting_id": game.setting_id,
                                "budget": int(budget),
                                "equivalent_budget": int(budget),
                                "realized_equivalent_cost": float(equivalent_cost),
                                "primary_task": True,
                                "evidence_scope": game.evidence_scope,
                                "split": split,
                                "estimand": "ordinary_shapley",
                                "modality": game.modality,
                                "model_family": game.model_family,
                                "fidelity_mechanism": game.fidelity_mechanism,
                                "residual_efficiency": residual_efficiency,
                                "game_hash": game.high.content_hash,
                                "low_game_hash": game.low.content_hash,
                                "market_mechanism": market.mechanism,
                                "diagnostics": diagnostics,
                            },
                        )
                    )
    return tuple(rows)


def load_smoke_games(cache_root: str | Path) -> tuple[StudyGame, ...]:
    root = Path(cache_root)
    family_mechanism = {
        "tree_ensemble": "ensemble_width",
        "boosting": "boosting_round_prefix",
        "neural_head": "training_epoch_prefix",
    }
    games = []
    for summary_path in sorted(root.glob("*/summary.json")):
        summary = json.loads(summary_path.read_text())
        manifest_hash = summary["manifest_hash"]
        tables = {}
        for fidelity in ("low", "high"):
            payload_path = summary_path.parent / "tables" / manifest_hash / fidelity / "values.partial.json"
            payload = json.loads(payload_path.read_text())
            values = {int(mask): float(value) for mask, value in payload["values"].items()}
            n_players = (len(values)).bit_length() - 1
            tables[fidelity] = CoalitionGameTable(
                tuple(f"o{index}" for index in range(n_players)),
                values,
                fidelity,
                metadata={"manifest_hash": manifest_hash},
            )
        games.append(
            StudyGame(
                summary["setting_id"],
                summary["modality"],
                summary["model_family"],
                family_mechanism[summary["model_family"]],
                tables["high"],
                tables["low"],
            )
        )
    if not games:
        raise ValueError(f"no completed smoke games under {root}")
    return tuple(games)


def _parse_ints(value: str) -> tuple[int, ...]:
    if ":" in value:
        start, stop = (int(item) for item in value.split(":", 1))
        return tuple(range(start, stop))
    return tuple(int(item) for item in value.split(","))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--budgets", default="192,224")
    parser.add_argument("--seeds", default="0:10")
    parser.add_argument("--methods", default=",".join(DEFAULT_METHODS))
    parser.add_argument("--setting-ids", help="comma-separated subset of cached settings")
    parser.add_argument("--low-cost-ratio", type=float, default=0.2)
    parser.add_argument("--official-repo", type=Path)
    parser.add_argument("--split", default="development")
    args = parser.parse_args()
    games = load_smoke_games(args.cache_root)
    if args.setting_ids:
        selected_ids = set(args.setting_ids.split(","))
        games = tuple(game for game in games if game.setting_id in selected_ids)
        missing = selected_ids - {game.setting_id for game in games}
        if missing:
            raise ValueError(f"unknown cached settings: {sorted(missing)}")
    rows = run_cached_table_study(
        games,
        budgets=_parse_ints(args.budgets),
        seeds=_parse_ints(args.seeds),
        method_ids=tuple(args.methods.split(",")),
        low_cost_ratio=args.low_cost_ratio,
        official_repo=args.official_repo,
        split=args.split,
    )
    args.output.mkdir(parents=True, exist_ok=True)
    raw = args.output / "raw_results.jsonl"
    existing = set()
    if raw.exists():
        existing = {
            json.loads(line)["run_id"] for line in raw.read_text().splitlines() if line.strip()
        }
    with raw.open("a") as stream:
        for row in rows:
            if row.run_id not in existing:
                stream.write(json.dumps(row.to_dict(), sort_keys=True) + "\n")
    ledger = [json.loads(line) for line in raw.read_text().splitlines() if line.strip()]
    manifest = {
        "games": sorted({row["metadata"]["setting_id"] for row in ledger}),
        "game_hashes": sorted({row["metadata"]["game_hash"] for row in ledger}),
        "budgets": sorted({row["metadata"]["budget"] for row in ledger}),
        "seeds": sorted({row["seed"] for row in ledger}),
        "methods": sorted({row["method_id"] for row in ledger}),
        "low_cost_ratio": args.low_cost_ratio,
        "evidence_scope": "controlled_cached_game",
    }
    (args.output / "study_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps({"rows": len(rows), "output": str(raw)}, sort_keys=True))


if __name__ == "__main__":
    main()


__all__ = [
    "DEFAULT_METHODS",
    "PAPER_COMPARATORS",
    "PaperComparator",
    "ProbeSelection",
    "StudyGame",
    "load_smoke_games",
    "resolve_amortized_disagreement",
    "resolve_probe_winners",
    "run_cached_table_study",
    "select_probe_gated_sampler",
]
