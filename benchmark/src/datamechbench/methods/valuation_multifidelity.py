"""Reusable multi-fidelity Shapley estimation and exact cost accounting."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Protocol, Sequence

import numpy as np

from ..coalition_games import CoalitionGameTable
from ..models import ValuationOutput
from .valuation_sota import evaluate_sota


class InapplicableBudgetError(ValueError):
    """A typed signal that a declared estimator cannot initialize."""

    status = "inapplicable_budget"

    def __init__(
        self,
        *,
        required_calls: int,
        available_calls: int,
        reason: str = "residual_initialization",
        diagnostics: Mapping[str, Any] | None = None,
    ) -> None:
        self.required_calls = int(required_calls)
        self.available_calls = int(available_calls)
        self.reason = str(reason)
        self.diagnostics = {
            "status": self.status,
            "reason": self.reason,
            "required_calls": self.required_calls,
            "available_calls": self.available_calls,
            **dict(diagnostics or {}),
        }
        super().__init__(
            f"budget provides {available_calls} residual calls; "
            f"at least {required_calls} are required"
        )


class StudyGameLike(Protocol):
    setting_id: str
    modality: str
    model_family: str
    fidelity_mechanism: str
    high: Any
    low: Any
    evidence_scope: str


@dataclass(frozen=True)
class ProbePlan:
    owner_subsets: tuple[tuple[int, ...], ...]
    local_to_global_masks: tuple[Mapping[int, int], ...]
    unique_high_masks: frozenset[int]


@dataclass(frozen=True)
class BudgetLedger:
    declared_budget: float
    low_cost_ratio: float
    probe_high_masks: frozenset[int]
    probe_medium_masks: frozenset[int]
    additional_medium_masks: frozenset[int]
    additional_high_calls: int
    equivalent_high_cost: float


@dataclass(frozen=True)
class ProbeRisk:
    probe_index: int
    median_mae: Mapping[str, float]
    winner: str


@dataclass(frozen=True)
class RoutingDecision:
    selected_method: str
    probe_risks: tuple[ProbeRisk, ...]
    fallback_used: bool


@dataclass(frozen=True)
class BudgetDebitedConfig:
    probe_players: int
    calibration_seeds: tuple[int, ...]
    calibration_budget: int
    candidates: tuple[str, ...] = (
        "elr_residual_leverage",
        "shapiq_svarm",
        "shapiq_leverage_shap",
    )
    fallback_method: str = "shapiq_svarm"

    def __post_init__(self) -> None:
        if self.probe_players < 2:
            raise ValueError("probe_players must be at least two")
        if not self.calibration_seeds:
            raise ValueError("calibration_seeds must not be empty")
        if self.calibration_budget < 2:
            raise ValueError("calibration_budget must be at least two")
        if not self.candidates or len(set(self.candidates)) != len(self.candidates):
            raise ValueError("candidates must be non-empty and unique")
        if self.fallback_method not in self.candidates:
            raise ValueError("fallback_method must be one of the candidates")


_PROBE_RISK_CACHE: dict[tuple[object, ...], tuple[ProbeRisk, ...]] = {}


def complementary_probe_plan(owner_ids: Sequence[str], k: int) -> ProbePlan:
    """Return first/last-k induced-subgame maps in manifest owner order."""

    owners = tuple(str(owner) for owner in owner_ids)
    if len(set(owners)) != len(owners):
        raise ValueError("owner IDs must be unique")
    if k < 2 or k > len(owners):
        raise ValueError("probe size must be between 2 and the owner count")
    subsets = (tuple(range(k)), tuple(range(len(owners) - k, len(owners))))
    mappings: list[dict[int, int]] = []
    unique_masks: set[int] = set()
    for subset in subsets:
        mapping = {
            local_mask: sum(
                ((local_mask >> local_index) & 1) << global_index
                for local_index, global_index in enumerate(subset)
            )
            for local_mask in range(1 << k)
        }
        mappings.append(mapping)
        unique_masks.update(mapping.values())
    return ProbePlan(subsets, tuple(mappings), frozenset(unique_masks))


def build_probe_games(
    game: StudyGameLike,
    plan: ProbePlan,
) -> tuple[StudyGameLike, ...]:
    """Materialize complete induced subgames described by a probe plan."""

    probes: list[StudyGameLike] = []
    for probe_index, (subset, mapping) in enumerate(
        zip(plan.owner_subsets, plan.local_to_global_masks, strict=True)
    ):
        owner_ids = tuple(game.high.owner_ids[index] for index in subset)
        probes.append(
            type(game)(
                f"{game.setting_id}-probe{probe_index}",
                game.modality,
                game.model_family,
                game.fidelity_mechanism,
                CoalitionGameTable(
                    owner_ids,
                    {mask: game.high.values[global_mask] for mask, global_mask in mapping.items()},
                    "high_probe",
                    metadata={"parent_hash": game.high.content_hash},
                ),
                CoalitionGameTable(
                    owner_ids,
                    {mask: game.low.values[global_mask] for mask, global_mask in mapping.items()},
                    "medium_probe",
                    metadata={"parent_hash": game.low.content_hash},
                ),
                evidence_scope="real_calibration_subgame",
            )
        )
    return tuple(probes)


def resolve_probe_risks(
    probe_risks: Iterable[ProbeRisk],
    *,
    fallback_method: str,
) -> RoutingDecision:
    """Select the unanimous probe winner, otherwise the declared fallback."""

    risks = tuple(probe_risks)
    if not risks:
        raise ValueError("probe_risks must not be empty")
    winners = {risk.winner for risk in risks}
    if len(winners) == 1:
        return RoutingDecision(next(iter(winners)), risks, False)
    return RoutingDecision(fallback_method, risks, True)


def make_budget_ledger(
    *,
    declared_budget: float,
    low_cost_ratio: float,
    probe_high_masks: Iterable[int] = (),
    probe_medium_masks: Iterable[int] = (),
    additional_medium_masks: Iterable[int] = (),
    additional_high_calls: int = 0,
) -> BudgetLedger:
    """Account unique probes and medium-only calls in high-call equivalents."""

    if not math.isfinite(declared_budget) or declared_budget < 0:
        raise ValueError("declared_budget must be finite and non-negative")
    if not math.isfinite(low_cost_ratio) or low_cost_ratio < 0:
        raise ValueError("low_cost_ratio must be finite and non-negative")
    if not isinstance(additional_high_calls, int) or additional_high_calls < 0:
        raise ValueError("additional_high_calls must be a non-negative integer")
    high_masks = frozenset(int(mask) for mask in probe_high_masks)
    emitted_medium = frozenset(int(mask) for mask in probe_medium_masks)
    medium_only = frozenset(int(mask) for mask in additional_medium_masks) - emitted_medium
    equivalent_cost = (
        float(len(high_masks) + additional_high_calls)
        + low_cost_ratio * len(medium_only)
    )
    if equivalent_cost > declared_budget + 1e-12:
        raise ValueError(
            f"realized equivalent cost {equivalent_cost} exceeds declared budget "
            f"{declared_budget}"
        )
    return BudgetLedger(
        float(declared_budget),
        float(low_cost_ratio),
        high_masks,
        emitted_medium,
        medium_only,
        additional_high_calls,
        equivalent_cost,
    )


def run_exact_low_residual(
    high: CoalitionGameTable,
    medium: CoalitionGameTable,
    *,
    residual_method: str,
    residual_budget: int,
    seed: int,
    ledger: BudgetLedger,
) -> ValuationOutput:
    """Compute exact medium Shapley plus an estimate of the residual game."""

    if high.owner_ids != medium.owner_ids:
        raise ValueError("high and medium games must have identical owner IDs")
    required_calls = (
        1 << len(high.owner_ids) if residual_method == "exact_table" else 2
    )
    if residual_budget < required_calls:
        raise InapplicableBudgetError(
            required_calls=required_calls,
            available_calls=residual_budget,
        )
    medium_truth = evaluate_sota(
        "exact_table",
        medium,
        budget=1 << len(medium.owner_ids),
        seed=0,
    )
    residual = CoalitionGameTable(
        high.owner_ids,
        {
            mask: high.values[mask] - medium.values[mask]
            for mask in high.values
        },
        "high_minus_medium_residual",
        metadata={
            "high_hash": high.content_hash,
            "medium_hash": medium.content_hash,
        },
    )
    residual_output = evaluate_sota(
        residual_method,
        residual,
        budget=residual_budget,
        seed=seed,
    )
    residual_calls = int(residual_output.utility_calls or residual_budget)
    return ValuationOutput(
        {
            owner: float(medium_truth.scores[owner])
            + float(residual_output.scores[owner])
            for owner in high.owner_ids
        },
        diagnostics={
            **residual_output.diagnostics,
            "backend": "exact_low_plus_residual",
            "base_estimator": residual_method,
            "low_calls": len(medium.values),
            "high_calls": residual_calls,
            "low_cost_ratio": ledger.low_cost_ratio,
            "equivalent_high_calls": ledger.equivalent_high_cost,
            "budget_ledger": {
                "probe_high_calls": len(ledger.probe_high_masks),
                "probe_medium_values": len(ledger.probe_medium_masks),
                "additional_medium_calls": len(ledger.additional_medium_masks),
                "additional_high_calls": ledger.additional_high_calls,
                "declared_budget": ledger.declared_budget,
            },
        },
        utility_calls=len(medium.values) + residual_calls,
    )


def calibrate_probe_risks(
    game: StudyGameLike,
    *,
    config: BudgetDebitedConfig,
    low_cost_ratio: float,
) -> tuple[ProbeRisk, ...]:
    """Estimate candidate risk on two complete induced subgames."""

    cache_key = (
        game.high.content_hash,
        game.low.content_hash,
        config,
        float(low_cost_ratio),
    )
    if cache_key in _PROBE_RISK_CACHE:
        return _PROBE_RISK_CACHE[cache_key]
    plan = complementary_probe_plan(game.high.owner_ids, config.probe_players)
    risks: list[ProbeRisk] = []
    for probe_index, probe in enumerate(build_probe_games(game, plan)):
        truth = evaluate_sota(
            "exact_table",
            probe.high,
            budget=len(probe.high.values),
            seed=0,
        )
        exact = np.asarray([truth.scores[owner] for owner in probe.high.owner_ids])
        errors: dict[str, list[float]] = {
            candidate: [] for candidate in config.candidates
        }
        for candidate in config.candidates:
            for calibration_seed in config.calibration_seeds:
                try:
                    if candidate == "elr_residual_leverage":
                        medium_calls = len(probe.low.values)
                        residual_budget = int(
                            config.calibration_budget
                            - medium_calls * low_cost_ratio
                        )
                        ledger = make_budget_ledger(
                            declared_budget=config.calibration_budget,
                            low_cost_ratio=low_cost_ratio,
                            additional_medium_masks=probe.low.values,
                            additional_high_calls=max(0, residual_budget),
                        )
                        output = run_exact_low_residual(
                            probe.high,
                            probe.low,
                            residual_method="shapiq_leverage_shap",
                            residual_budget=residual_budget,
                            seed=calibration_seed,
                            ledger=ledger,
                        )
                    else:
                        output = evaluate_sota(
                            candidate,
                            probe.high,
                            budget=config.calibration_budget,
                            seed=calibration_seed,
                        )
                except (InapplicableBudgetError, ValueError):
                    errors[candidate].append(float("inf"))
                    continue
                predicted = np.asarray(
                    [output.scores[owner] for owner in probe.high.owner_ids]
                )
                errors[candidate].append(float(np.mean(np.abs(predicted - exact))))
        medians = {
            candidate: float(np.median(candidate_errors))
            for candidate, candidate_errors in errors.items()
        }
        winner = min(
            config.candidates,
            key=lambda name: (medians[name], config.candidates.index(name)),
        )
        risks.append(ProbeRisk(probe_index, medians, winner))
    result = tuple(risks)
    _PROBE_RISK_CACHE[cache_key] = result
    return result


def select_budget_debited_method(
    game: StudyGameLike,
    *,
    budget: int,
    config: BudgetDebitedConfig,
    low_cost_ratio: float,
    seed: int,
) -> ValuationOutput:
    """Route and estimate under one budget that includes probe acquisition."""

    if not isinstance(budget, int) or budget < 0:
        raise ValueError("budget must be a non-negative integer")
    plan = complementary_probe_plan(game.high.owner_ids, config.probe_players)
    probe_cost = len(plan.unique_high_masks)
    if probe_cost > budget:
        raise InapplicableBudgetError(
            required_calls=probe_cost,
            available_calls=budget,
            reason="probe_cost_exceeds_budget",
            diagnostics={"probe_high_calls": probe_cost, "declared_budget": budget},
        )
    probe_risks = calibrate_probe_risks(
        game,
        config=config,
        low_cost_ratio=low_cost_ratio,
    )
    decision = resolve_probe_risks(
        probe_risks,
        fallback_method=config.fallback_method,
    )
    common = {
        "selected_method": decision.selected_method,
        "probe_winners": tuple(risk.winner for risk in probe_risks),
        "probe_median_mae": tuple(dict(risk.median_mae) for risk in probe_risks),
        "fallback_used": decision.fallback_used,
        "probe_players": config.probe_players,
        "calibration_budget": config.calibration_budget,
        "calibration_seeds": config.calibration_seeds,
        "probe_high_calls": probe_cost,
        "probe_medium_values": probe_cost,
        "declared_budget": budget,
        "calibration_cost_accounting": "strict_one_shot_debited",
        "production_warm_start_reused": False,
    }
    if decision.selected_method == "elr_residual_leverage":
        all_masks = frozenset(game.low.values)
        additional_medium_masks = all_masks - plan.unique_high_masks
        available = budget - probe_cost - low_cost_ratio * len(additional_medium_masks)
        production_budget = math.floor(available + 1e-12)
        if production_budget < 2:
            raise InapplicableBudgetError(
                required_calls=2,
                available_calls=max(0, production_budget),
                reason="residual_initialization_after_probe_and_medium",
                diagnostics={
                    **common,
                    "additional_medium_calls": len(additional_medium_masks),
                    "remaining_equivalent_budget": available,
                },
            )
        conservative_ledger = make_budget_ledger(
            declared_budget=budget,
            low_cost_ratio=low_cost_ratio,
            probe_high_masks=plan.unique_high_masks,
            probe_medium_masks=plan.unique_high_masks,
            additional_medium_masks=all_masks,
            additional_high_calls=production_budget,
        )
        output = run_exact_low_residual(
            game.high,
            game.low,
            residual_method="shapiq_leverage_shap",
            residual_budget=production_budget,
            seed=seed,
            ledger=conservative_ledger,
        )
        production_calls = int(output.diagnostics["high_calls"])
        realized = make_budget_ledger(
            declared_budget=budget,
            low_cost_ratio=low_cost_ratio,
            probe_high_masks=plan.unique_high_masks,
            probe_medium_masks=plan.unique_high_masks,
            additional_medium_masks=all_masks,
            additional_high_calls=production_calls,
        )
        return ValuationOutput(
            output.scores,
            diagnostics={
                **output.diagnostics,
                **common,
                "backend": "budget_debited_probe_gated_elr",
                "additional_medium_calls": len(additional_medium_masks),
                "production_high_budget": production_budget,
                "production_high_calls": production_calls,
                "realized_equivalent_cost": realized.equivalent_high_cost,
                "equivalent_high_calls": realized.equivalent_high_cost,
            },
            utility_calls=probe_cost + len(additional_medium_masks) + production_calls,
        )

    production_budget = budget - probe_cost
    if production_budget < 2:
        raise InapplicableBudgetError(
            required_calls=2,
            available_calls=max(0, production_budget),
            reason="direct_initialization_after_probe",
            diagnostics=common,
        )
    output = evaluate_sota(
        decision.selected_method,
        game.high,
        budget=production_budget,
        seed=seed,
    )
    production_calls = int(output.utility_calls or production_budget)
    realized = make_budget_ledger(
        declared_budget=budget,
        low_cost_ratio=low_cost_ratio,
        probe_high_masks=plan.unique_high_masks,
        probe_medium_masks=plan.unique_high_masks,
        additional_high_calls=production_calls,
    )
    return ValuationOutput(
        output.scores,
        diagnostics={
            **output.diagnostics,
            **common,
            "backend": "budget_debited_probe_gated_direct",
            "additional_medium_calls": 0,
            "production_high_budget": production_budget,
            "production_high_calls": production_calls,
            "realized_equivalent_cost": realized.equivalent_high_cost,
            "equivalent_high_calls": realized.equivalent_high_cost,
        },
        utility_calls=probe_cost + production_calls,
    )


__all__ = [
    "BudgetDebitedConfig",
    "BudgetLedger",
    "InapplicableBudgetError",
    "ProbePlan",
    "ProbeRisk",
    "RoutingDecision",
    "StudyGameLike",
    "build_probe_games",
    "calibrate_probe_risks",
    "complementary_probe_plan",
    "make_budget_ledger",
    "resolve_probe_risks",
    "run_exact_low_residual",
    "select_budget_debited_method",
]
