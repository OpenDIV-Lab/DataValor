"""Capability-routed metric records shared by benchmark reports."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from itertools import combinations
from typing import Any, Iterable, Mapping

import numpy as np
from scipy.stats import kendalltau, spearmanr
from sklearn.metrics import average_precision_score, f1_score, roc_auc_score

from .data import OwnerDataset
from .mechanism_bridge import bridge_valuation_scores
from .models import (
    MarketOutcome,
    MethodSpec,
    ProcurementCase,
    ProcurementInput,
    TradeCase,
    ValuationCase,
    ValuationOutput,
)
from .properties import (
    dummy_violation,
    efficiency_residual,
    least_core_max_violation,
    symmetry_gap,
)
from .settings.valuation_mechanisms import ValuationMechanismSetting
from .stress import bid_reports, cost_reports


@dataclass(frozen=True)
class MetricValue:
    value: Any = None
    applicable: bool = True
    reason: str | None = None

    @classmethod
    def na(cls, reason: str) -> "MetricValue":
        return cls(value=None, applicable=False, reason=reason)

    def to_dict(self) -> dict[str, Any]:
        return {"value": self.value, "applicable": self.applicable, "reason": self.reason}


def _ordered_scores(case: ValuationCase, output: ValuationOutput) -> list[float]:
    return [float(output.scores[owner]) for owner in case.owner_ids]


def _stability(
    case: ValuationCase,
    output: ValuationOutput,
    peers: Iterable[object],
) -> MetricValue:
    comparable = [output]
    for peer in peers:
        if isinstance(peer, ValuationOutput) and set(peer.scores) == set(case.owner_ids):
            comparable.append(peer)
    if len(comparable) < 2:
        return MetricValue.na("missing_peer_outputs")
    vectors = [_ordered_scores(case, item) for item in comparable]
    correlations = [
        float(kendalltau(left, right).statistic)
        for left, right in combinations(vectors, 2)
    ]
    finite = [value for value in correlations if np.isfinite(value)]
    return MetricValue(float(np.mean(finite))) if finite else MetricValue.na("constant_scores")


def _replication_gain(
    case: ValuationCase,
    output: ValuationOutput,
    peers: Iterable[object],
) -> MetricValue:
    duplicate_pair = case.metadata.get("duplicate_pair")
    if not duplicate_pair:
        return MetricValue.na("not_replication_case")
    original, duplicate = duplicate_pair
    for peer in peers:
        if not (isinstance(peer, tuple) and len(peer) == 2):
            continue
        peer_case, peer_output = peer
        if (
            isinstance(peer_case, ValuationCase)
            and isinstance(peer_output, ValuationOutput)
            and original in peer_output.scores
            and duplicate not in peer_output.scores
        ):
            gain = (
                float(output.scores[original])
                + float(output.scores[duplicate])
                - float(peer_output.scores[original])
            )
            return MetricValue(gain)
    return MetricValue.na("missing_clean_peer_output")


def _rank(scores: Mapping[str, float], owner: str) -> float:
    ordering = sorted(scores, key=lambda item: (-float(scores[item]), item))
    return ordering.index(owner) / max(1, len(ordering) - 1)


def _replication_attack_metrics(
    case: ValuationCase,
    output: ValuationOutput,
    peers: Iterable[object],
) -> Mapping[str, MetricValue]:
    owner = case.metadata.get("replicated_owner")
    factor = case.metadata.get("replication_factor")
    baseline_id = case.metadata.get("replication_baseline_case_id")
    names = (
        "replication_reward_share_gain",
        "replication_score_inflation_ratio",
        "characteristic_replication_inflation_ratio",
        "replication_owner_rank_change",
    )
    if owner not in output.scores or factor is None or not baseline_id:
        return {name: MetricValue.na("not_replication_attack_case") for name in names}
    if int(factor) == 1:
        return {
            "replication_reward_share_gain": MetricValue(0.0),
            "replication_score_inflation_ratio": MetricValue(1.0),
            "characteristic_replication_inflation_ratio": MetricValue(1.0),
            "replication_owner_rank_change": MetricValue(0.0),
        }
    baseline_output = None
    for peer in peers:
        if not (isinstance(peer, tuple) and len(peer) == 2):
            continue
        peer_case, peer_output = peer
        if (
            isinstance(peer_case, ValuationCase)
            and peer_case.case_id == baseline_id
            and isinstance(peer_output, ValuationOutput)
        ):
            baseline_output = peer_output
            break
    if baseline_output is None or owner not in baseline_output.scores:
        return {name: MetricValue.na("missing_replication_baseline") for name in names}

    current_positive = {key: max(0.0, float(value)) for key, value in output.scores.items()}
    clean_positive = {
        key: max(0.0, float(value)) for key, value in baseline_output.scores.items()
    }
    current_total = sum(current_positive.values())
    clean_total = sum(clean_positive.values())
    if current_total > 0 and clean_total > 0:
        share_gain = MetricValue(
            current_positive[owner] / current_total
            - clean_positive[owner] / clean_total
        )
    else:
        share_gain = MetricValue.na("nonpositive_total_reward")

    clean_score = float(baseline_output.scores[owner])
    current_score = float(output.scores[owner])
    score_ratio = (
        MetricValue(current_score / clean_score)
        if clean_score > 0 and current_score >= 0
        else MetricValue.na("nonpositive_baseline_or_attacked_score")
    )
    clean_characteristic = baseline_output.diagnostics.get("characteristic_value")
    current_characteristic = output.diagnostics.get("characteristic_value")
    characteristic_ratio = (
        MetricValue(float(current_characteristic) / float(clean_characteristic))
        if clean_characteristic is not None
        and current_characteristic is not None
        and float(clean_characteristic) > 0
        else MetricValue.na("characteristic_value_unavailable")
    )
    rank_change = MetricValue(
        _rank(baseline_output.scores, owner) - _rank(output.scores, owner)
    )
    return {
        "replication_reward_share_gain": share_gain,
        "replication_score_inflation_ratio": score_ratio,
        "characteristic_replication_inflation_ratio": characteristic_ratio,
        "replication_owner_rank_change": rank_change,
    }


def evaluate_valuation_metrics(
    case: ValuationCase,
    output: ValuationOutput,
    oracle_output: ValuationOutput | None = None,
    peer_outputs: Iterable[object] = (),
) -> Mapping[str, MetricValue]:
    peers = tuple(peer_outputs)
    if oracle_output is None:
        mae = MetricValue.na("missing_oracle_output")
        spearman = MetricValue.na("missing_oracle_output")
    else:
        scores = np.asarray(_ordered_scores(case, output), dtype=float)
        oracle = np.asarray(_ordered_scores(case, oracle_output), dtype=float)
        mae = MetricValue(float(np.mean(np.abs(scores - oracle))))
        correlation = float(spearmanr(scores, oracle).statistic)
        spearman = MetricValue(correlation) if np.isfinite(correlation) else MetricValue.na("constant_scores")

    dataset = case.metadata.get("owner_dataset")
    if isinstance(dataset, OwnerDataset):
        top_k = max(1, min(int(output.diagnostics.get("top_k", 3)), len(case.owner_ids)))
        selected = tuple(
            sorted(case.owner_ids, key=lambda owner: (-output.scores[owner], owner))[:top_k]
        )
        topk = MetricValue(dataset.utility_for_owners(selected, use_test=True))
    else:
        topk = MetricValue.na("missing_test_dataset")

    bad_owner = case.metadata.get("bad_owner")
    if bad_owner in output.scores:
        ranking = sorted(case.owner_ids, key=lambda owner: (-output.scores[owner], owner))
        normalized_rank = ranking.index(bad_owner) / max(1, len(ranking) - 1)
        bad_rank = MetricValue(float(normalized_rank))
    else:
        bad_rank = MetricValue.na("missing_bad_owner")

    calls = (
        MetricValue(int(output.utility_calls))
        if output.utility_calls is not None
        else MetricValue.na("missing_utility_calls")
    )
    runtime = output.diagnostics.get("runtime_seconds")
    runtime_metric = (
        MetricValue(float(runtime)) if runtime is not None else MetricValue.na("missing_runtime")
    )
    corrupted = frozenset(case.metadata.get("corrupted_owners", ()))
    if corrupted and corrupted != frozenset(case.owner_ids):
        labels = np.asarray([owner in corrupted for owner in case.owner_ids], dtype=int)
        anomaly_scores = np.asarray([-float(output.scores[owner]) for owner in case.owner_ids])
        corruption_auroc = MetricValue(float(roc_auc_score(labels, anomaly_scores)))
        corruption_auprc = MetricValue(float(average_precision_score(labels, anomaly_scores)))
        predicted = set(
            sorted(case.owner_ids, key=lambda owner: (output.scores[owner], owner))[
                : len(corrupted)
            ]
        )
        predictions = np.asarray([owner in predicted for owner in case.owner_ids], dtype=int)
        corruption_f1 = MetricValue(float(f1_score(labels, predictions)))
    else:
        corruption_auroc = MetricValue.na("missing_corruption_labels")
        corruption_auprc = MetricValue.na("missing_corruption_labels")
        corruption_f1 = MetricValue.na("missing_corruption_labels")

    if isinstance(dataset, OwnerDataset):
        ranking = sorted(case.owner_ids, key=lambda owner: (-output.scores[owner], owner))
        addition_values = [dataset.utility_for_owners(ranking[:count], use_test=True) for count in range(len(ranking) + 1)]
        removal_values = [dataset.utility_for_owners(ranking[count:], use_test=True) for count in range(len(ranking) + 1)]
        x_axis = np.linspace(0.0, 1.0, len(ranking) + 1)
        addition_auc = MetricValue(float(np.trapezoid(addition_values, x_axis)))
        removal_auc = MetricValue(float(np.trapezoid(removal_values, x_axis)))
    else:
        addition_auc = MetricValue.na("missing_test_dataset")
        removal_auc = MetricValue.na("missing_test_dataset")

    deletion_effects = case.metadata.get("owner_deletion_effects")
    if isinstance(deletion_effects, Mapping) and set(deletion_effects) == set(case.owner_ids):
        correlation = float(
            spearmanr(
                [output.scores[owner] for owner in case.owner_ids],
                [deletion_effects[owner] for owner in case.owner_ids],
            ).statistic
        )
        utility_recovery = MetricValue(correlation) if np.isfinite(correlation) else MetricValue.na("constant_scores")
    else:
        utility_recovery = MetricValue.na("missing_owner_deletion_effects")

    efficiency = efficiency_residual(case, output)
    dummy = dummy_violation(case, output)
    symmetry = symmetry_gap(case, output)
    least_core = least_core_max_violation(case, output)
    split_pair = case.metadata.get("split_pair")
    split_change = (
        MetricValue(
            sum(float(output.scores[owner]) for owner in split_pair)
            - float(case.metadata["unsplit_value"])
        )
        if split_pair and "unsplit_value" in case.metadata
        else MetricValue.na("not_owner_split_case")
    )
    replication_metrics = _replication_attack_metrics(case, output, peers)
    return {
        "score_mae": mae,
        "score_spearman": spearman,
        "topk_test_utility": topk,
        "bad_owner_rank": bad_rank,
        "corruption_auroc": corruption_auroc,
        "corruption_auprc": corruption_auprc,
        "corruption_topk_f1": corruption_f1,
        "addition_auc": addition_auc,
        "removal_auc": removal_auc,
        "utility_recovery": utility_recovery,
        "efficiency_residual": MetricValue(efficiency),
        "dummy_violation": MetricValue(dummy) if dummy is not None else MetricValue.na("missing_dummy_owners"),
        "symmetry_gap": MetricValue(symmetry) if symmetry is not None else MetricValue.na("missing_symmetric_groups"),
        "least_core_max_violation": MetricValue(least_core) if least_core is not None else MetricValue.na("not_least_core_output"),
        "replication_gain": _replication_gain(case, output, peers),
        **replication_metrics,
        "split_payoff_change": split_change,
        "kendall_stability": _stability(case, output, peers),
        "utility_calls": calls,
        "runtime_seconds": runtime_metric,
    }


def _ndcg(predicted: np.ndarray, truth: np.ndarray) -> float:
    order = np.argsort(-predicted, kind="stable")
    ideal = np.argsort(-truth, kind="stable")
    gains = np.maximum(truth, 0.0)
    discounts = np.log2(np.arange(2, len(truth) + 2))
    denominator = float(np.sum(gains[ideal] / discounts))
    return float(np.sum(gains[order] / discounts) / denominator) if denominator else 1.0


def _gini(values: list[float]) -> MetricValue:
    array = np.asarray(values, dtype=float)
    if not len(array) or np.allclose(array.sum(), 0.0):
        return MetricValue.na("no_positive_payments")
    difference = np.abs(array[:, None] - array[None, :]).sum()
    return MetricValue(float(difference / (2 * len(array) * array.sum())))


def evaluate_valuation_market_metrics(
    setting: ValuationMechanismSetting,
    output: ValuationOutput,
    oracle_output: ValuationOutput | None,
) -> Mapping[str, MetricValue]:
    """Evaluate estimation and market consequences under one common bridge."""
    predicted_decision = bridge_valuation_scores(setting, output.scores)
    runtime = output.diagnostics.get("time_to_error")
    time_to_error = (
        MetricValue(float(runtime))
        if runtime is not None
        else MetricValue.na("missing_error_trace")
    )
    predicted_payments = [
        float(predicted_decision.payments.get(owner, Decimal("0")))
        for owner in setting.owner_ids
    ]
    total_payment = sum(predicted_decision.payments.values(), Decimal("0"))
    buyer_utility = predicted_decision.welfare - float(total_payment)
    ir_violations = sum(
        predicted_decision.payments.get(owner, Decimal("0")) < setting.costs[owner]
        for owner in predicted_decision.selected_ids
        if owner in setting.costs and owner in predicted_decision.payments
    )
    duplicate_spend = (
        MetricValue(
            float(
                sum(
                    (
                        predicted_decision.payments.get(owner, Decimal("0"))
                        for owner in setting.duplicate_owners
                    ),
                    Decimal("0"),
                )
            )
        )
        if setting.duplicate_owners
        else MetricValue.na("missing_duplicate_owners")
    )
    noisy_spend = (
        MetricValue(
            float(
                sum(
                    (
                        predicted_decision.payments.get(owner, Decimal("0"))
                        for owner in setting.noisy_owners
                    ),
                    Decimal("0"),
                )
            )
        )
        if setting.noisy_owners
        else MetricValue.na("missing_noisy_owners")
    )
    base = {
        "time_to_error": time_to_error,
        "payment_gini": _gini(predicted_payments),
        "valuation_buyer_utility": MetricValue(float(buyer_utility)),
        "valuation_budget_violation": MetricValue(total_payment > setting.budget),
        "valuation_ir_violation_count": MetricValue(int(ir_violations)),
        "duplicate_spend": duplicate_spend,
        "noisy_spend": noisy_spend,
    }
    oracle_metric_names = (
        "score_ndcg",
        "normalized_score_mae",
        "max_score_error",
        "payment_mae",
        "payment_rank_correlation",
        "payment_conservation_error",
        "welfare_regret",
        "allocation_regret",
        "decision_flip_rate",
        "sequential_stopping_regret",
    )
    if oracle_output is None:
        return {
            **base,
            **{
                name: MetricValue.na("missing_oracle_output")
                for name in oracle_metric_names
            },
        }

    predicted = np.asarray(
        [float(output.scores[owner]) for owner in setting.owner_ids], dtype=float
    )
    truth = np.asarray(
        [float(oracle_output.scores[owner]) for owner in setting.owner_ids], dtype=float
    )
    oracle_decision = bridge_valuation_scores(setting, oracle_output.scores)
    oracle_payments = [
        float(oracle_decision.payments.get(owner, Decimal("0")))
        for owner in setting.owner_ids
    ]
    scale = max(float(np.mean(np.abs(truth))), 1e-12)
    if np.ptp(predicted_payments) == 0 or np.ptp(oracle_payments) == 0:
        payment_rank = MetricValue.na("constant_payments")
    else:
        payment_correlation = float(
            spearmanr(predicted_payments, oracle_payments).statistic
        )
        payment_rank = MetricValue(payment_correlation)
    predicted_set = set(predicted_decision.selected_ids)
    oracle_set = set(oracle_decision.selected_ids)
    realized_welfare = sum(
        float(oracle_output.scores[owner]) for owner in predicted_decision.selected_ids
    )
    oracle_welfare = sum(
        float(oracle_output.scores[owner]) for owner in oracle_decision.selected_ids
    )
    sequential_regret = (
        MetricValue(abs((predicted_decision.stop_index or 0) - (oracle_decision.stop_index or 0)))
        if setting.mechanism == "sequential_acquisition"
        else MetricValue.na("not_sequential_acquisition")
    )
    return {
        **base,
        "score_ndcg": MetricValue(_ndcg(predicted, truth)),
        "normalized_score_mae": MetricValue(float(np.mean(np.abs(predicted - truth))) / scale),
        "max_score_error": MetricValue(float(np.max(np.abs(predicted - truth)))),
        "payment_mae": MetricValue(float(np.mean(np.abs(np.asarray(predicted_payments) - np.asarray(oracle_payments))))),
        "payment_rank_correlation": payment_rank,
        "payment_conservation_error": MetricValue(
            abs(sum(predicted_payments) - sum(oracle_payments))
        ),
        "welfare_regret": MetricValue(max(0.0, oracle_welfare - realized_welfare)),
        "allocation_regret": MetricValue(
            len(predicted_set.symmetric_difference(oracle_set)) / len(setting.owner_ids)
        ),
        "decision_flip_rate": MetricValue(
            len(predicted_set.symmetric_difference(oracle_set)) / len(setting.owner_ids)
        ),
        "sequential_stopping_regret": sequential_regret,
    }


def evaluate_procurement_metrics(
    case: ProcurementCase,
    output: MarketOutcome,
    spec: MethodSpec,
    oracle_output: MarketOutcome | None = None,
    *,
    method: Any | None = None,
    seed: int = 0,
) -> Mapping[str, MetricValue]:
    realized = float(case.public.utility(output.selected_ids))
    empty_utility = float(case.public.utility(()))
    if oracle_output is None:
        oracle_ratio = MetricValue.na("missing_oracle_output")
        normalized_oracle_gain_ratio = MetricValue.na("missing_oracle_output")
        oracle_metric = MetricValue.na("missing_oracle_output")
    else:
        oracle_utility = float(case.public.utility(oracle_output.selected_ids))
        oracle_ratio = MetricValue(realized / oracle_utility) if oracle_utility else MetricValue.na("zero_oracle_utility")
        oracle_gain = oracle_utility - empty_utility
        normalized_oracle_gain_ratio = (
            MetricValue((realized - empty_utility) / oracle_gain)
            if abs(oracle_gain) > 1e-15
            else MetricValue.na("zero_oracle_gain_over_empty_set")
        )
        oracle_metric = MetricValue(oracle_utility)
    efficiency_loss = (
        MetricValue(1.0 - float(oracle_ratio.value))
        if oracle_ratio.applicable
        else MetricValue.na(oracle_ratio.reason or "missing_oracle_output")
    )
    singleton_share = case.metadata.get("largest_singleton_share")
    query_count = output.diagnostics.get("utility_query_count")
    value_oracle_queries = (
        MetricValue(int(query_count))
        if query_count is not None
        else MetricValue.na("method_does_not_report_value_oracle_queries")
    )

    total_payment = sum((payment.amount for payment in output.payments), start=Decimal("0"))
    budget_violation = total_payment > case.public.budget
    budget_used = (
        float(total_payment / case.public.budget)
        if case.public.budget
        else 0.0
    )
    payment_sellers = {payment.payee_id for payment in output.payments}
    if "truthful_payments" in spec.capabilities and not payment_sellers.issubset(case.true_costs):
        ir = MetricValue.na("missing_true_types")
    elif "truthful_payments" in spec.capabilities:
        violations = sum(
            payment.amount < case.true_costs[payment.payee_id]
            for payment in output.payments
            if payment.payee_id in case.true_costs
        )
        ir = MetricValue(int(violations))
    else:
        ir = MetricValue.na("truthful_payments_unsupported")

    dataset = case.metadata.get("owner_dataset")
    if isinstance(dataset, OwnerDataset) and dataset.duplicate_of:
        duplicate_spend = sum(
            (payment.amount for payment in output.payments if payment.payee_id in dataset.duplicate_of),
            start=Decimal("0"),
        )
        duplicate_ratio = MetricValue(float(duplicate_spend / total_payment) if total_payment else 0.0)
    else:
        duplicate_ratio = MetricValue.na("missing_duplicate_bundle")
    if isinstance(dataset, OwnerDataset) and any(dataset.noise_rates.values()):
        noisy_spend = sum(
            (
                payment.amount
                for payment in output.payments
                if dataset.noise_rates.get(payment.payee_id, 0.0) > 0
            ),
            start=Decimal("0"),
        )
        noisy_ratio = MetricValue(float(noisy_spend / total_payment) if total_payment else 0.0)
    else:
        noisy_ratio = MetricValue.na("missing_noisy_bundle")

    if "strategic_reports" not in spec.capabilities:
        deviation = MetricValue.na("strategic_reports_unsupported")
        profitable_count = MetricValue.na("strategic_reports_unsupported")
    elif method is None:
        deviation = MetricValue.na("missing_method_runner")
        profitable_count = MetricValue.na("missing_method_runner")
    elif set(case.public.seller_ids) - set(case.true_costs):
        deviation = MetricValue.na("missing_true_types")
        profitable_count = MetricValue.na("missing_true_types")
    else:
        truthful_utilities = {
            seller: sum(
                (payment.amount for payment in output.payments if payment.payee_id == seller),
                start=Decimal("0"),
            )
            - (case.true_costs[seller] if seller in output.selected_ids else Decimal("0"))
            for seller in case.public.seller_ids
        }
        gains = []
        for (seller, _), public in cost_reports(case).items():
            alternative = method.allocate(public, seed)
            alternative_utility = sum(
                (payment.amount for payment in alternative.payments if payment.payee_id == seller),
                start=Decimal("0"),
            ) - (case.true_costs[seller] if seller in alternative.selected_ids else Decimal("0"))
            gains.append(max(Decimal("0"), alternative_utility - truthful_utilities[seller]))
        positive = [gain for gain in gains if gain > Decimal("1e-12")]
        deviation = MetricValue(float(max(gains, default=Decimal("0"))))
        profitable_count = MetricValue(len(positive))

    if method is not None and "strategic_reports" in spec.capabilities:
        monotonicity_violations = 0
        critical_gaps: list[float] = []
        payment_by_seller = {
            payment.payee_id: payment.amount for payment in output.payments
        }
        for seller in case.public.seller_ids:
            original = case.public.reported_costs[seller]
            lower = original / Decimal("2")
            lower_public = ProcurementInput(
                seller_ids=case.public.seller_ids,
                reported_costs={**case.public.reported_costs, seller: lower},
                budget=case.public.budget,
                utility=case.public.utility,
                seller_values=case.public.seller_values,
                metadata=case.public.metadata,
            )
            if seller in output.selected_ids and seller not in method.allocate(lower_public, seed).selected_ids:
                monotonicity_violations += 1
            if seller not in output.selected_ids or seller not in payment_by_seller:
                continue
            low = original
            high = case.public.budget
            if seller in method.allocate(
                ProcurementInput(
                    seller_ids=case.public.seller_ids,
                    reported_costs={**case.public.reported_costs, seller: high},
                    budget=case.public.budget,
                    utility=case.public.utility,
                    seller_values=case.public.seller_values,
                    metadata=case.public.metadata,
                ),
                seed,
            ).selected_ids:
                threshold = high
            else:
                for _ in range(32):
                    midpoint = (low + high) / Decimal("2")
                    public = ProcurementInput(
                        seller_ids=case.public.seller_ids,
                        reported_costs={**case.public.reported_costs, seller: midpoint},
                        budget=case.public.budget,
                        utility=case.public.utility,
                        seller_values=case.public.seller_values,
                        metadata=case.public.metadata,
                    )
                    if seller in method.allocate(public, seed).selected_ids:
                        low = midpoint
                    else:
                        high = midpoint
                threshold = low
            critical_gaps.append(abs(float(payment_by_seller[seller] - threshold)))
        allocation_monotonicity = MetricValue(monotonicity_violations)
        critical_payment_gap = (
            MetricValue(max(critical_gaps))
            if critical_gaps
            else MetricValue.na("no_paid_winners")
        )
    else:
        allocation_monotonicity = MetricValue.na("strategic_audit_unavailable")
        critical_payment_gap = MetricValue.na("strategic_audit_unavailable")

    if output.payments:
        buyer_utility = MetricValue(realized - float(total_payment))
        selected_cost = sum(
            (case.true_costs[seller] for seller in output.selected_ids if seller in case.true_costs),
            Decimal("0"),
        )
        seller_surplus = MetricValue(float(total_payment - selected_cost))
    else:
        buyer_utility = MetricValue.na("missing_payments")
        seller_surplus = MetricValue.na("missing_payments")

    return {
        "realized_utility": MetricValue(realized),
        "oracle_ratio": oracle_ratio,
        "normalized_oracle_gain_ratio": normalized_oracle_gain_ratio,
        "oracle_utility": oracle_metric,
        "procurement_efficiency_loss": efficiency_loss,
        "largest_singleton_share": (
            MetricValue(float(singleton_share))
            if singleton_share is not None
            else MetricValue.na("setting_does_not_declare_singleton_share")
        ),
        "value_oracle_queries": value_oracle_queries,
        "total_payment": MetricValue(str(total_payment)) if output.payments else MetricValue.na("missing_payments"),
        "budget_used_ratio": MetricValue(budget_used) if output.payments else MetricValue.na("missing_payments"),
        "budget_violation": MetricValue(bool(budget_violation)) if output.payments else MetricValue.na("missing_payments"),
        "seller_ir_violation_count": ir,
        "duplicate_spend_ratio": duplicate_ratio,
        "noisy_spend_ratio": noisy_ratio,
        "max_deviation_gain": deviation,
        "profitable_deviation_count": profitable_count,
        "allocation_monotonicity_violation": allocation_monotonicity,
        "critical_payment_gap": critical_payment_gap,
        "buyer_utility": buyer_utility,
        "seller_surplus": seller_surplus,
    }


def _allocation_pairs(output: MarketOutcome) -> tuple[tuple[str, str], ...]:
    return tuple(
        (allocation.actor_id, allocation.counterparty_id)
        for allocation in output.allocations
        if allocation.counterparty_id is not None
    )


def evaluate_trading_metrics(
    case: TradeCase,
    output: MarketOutcome,
    spec: MethodSpec,
    oracle_output: MarketOutcome | None = None,
    *,
    method: Any | None = None,
    seed: int = 0,
) -> Mapping[str, MetricValue]:
    pairs = _allocation_pairs(output)
    truth_complete = all(
        buyer in case.true_values and seller in case.true_costs for buyer, seller in pairs
    )
    realized = (
        sum(
            (case.true_values[buyer] - case.true_costs[seller] for buyer, seller in pairs),
            start=Decimal("0"),
        )
        if truth_complete
        else None
    )
    oracle_gft: Decimal | None = None
    if not truth_complete:
        ratio = MetricValue.na("missing_true_types")
        oracle_gft_metric = MetricValue.na("missing_true_types")
    elif oracle_output is None:
        ratio = MetricValue.na("missing_oracle_output")
        oracle_gft_metric = MetricValue.na("missing_oracle_output")
    else:
        oracle_gft = sum(
            (
                case.true_values[buyer] - case.true_costs[seller]
                for buyer, seller in _allocation_pairs(oracle_output)
            ),
            start=Decimal("0"),
        )
        ratio = MetricValue(float(realized / oracle_gft)) if oracle_gft else MetricValue.na("zero_oracle_gain")
        oracle_gft_metric = MetricValue(float(oracle_gft))

    allocated_buyers = {buyer for buyer, _ in pairs}
    allocated_sellers = {seller for _, seller in pairs}
    buyer_payments = {
        buyer: sum(
            (payment.amount for payment in output.payments if payment.payer_id == buyer),
            start=Decimal("0"),
        )
        for buyer in case.public.buyer_ids
    }
    seller_receipts = {
        seller: sum(
            (payment.amount for payment in output.payments if payment.payee_id == seller),
            start=Decimal("0"),
        )
        for seller in case.public.seller_ids
    }
    buyer_surplus = (
        sum(
            (
                (case.true_values[buyer] if buyer in allocated_buyers else Decimal("0"))
                - buyer_payments[buyer]
                for buyer in case.public.buyer_ids
            ),
            start=Decimal("0"),
        )
        if truth_complete
        else None
    )
    seller_revenue = sum(seller_receipts.values(), start=Decimal("0"))
    platform_in = sum(
        (payment.amount for payment in output.payments if payment.payee_id == "platform"),
        start=Decimal("0"),
    )
    platform_out = sum(
        (payment.amount for payment in output.payments if payment.payer_id == "platform"),
        start=Decimal("0"),
    )
    auctioneer_surplus = platform_in - platform_out
    total_buyer_payment = sum(
        (
            payment.amount
            for payment in output.payments
            if payment.payer_id in case.public.buyer_ids
        ),
        Decimal("0"),
    )
    total_seller_receipt = sum(
        (
            payment.amount
            for payment in output.payments
            if payment.payee_id in case.public.seller_ids
        ),
        Decimal("0"),
    )
    strong_budget_balance = MetricValue(total_buyer_payment == total_seller_receipt) if output.payments else MetricValue.na("missing_payments")

    if "payments" in spec.capabilities and not truth_complete:
        individual_rationality = MetricValue.na("missing_true_types")
        weak_budget_balance = MetricValue(bool(auctioneer_surplus >= 0))
    elif "payments" in spec.capabilities:
        buyer_ir = all(
            (case.true_values[buyer] if buyer in allocated_buyers else Decimal("0"))
            - buyer_payments[buyer]
            >= 0
            for buyer in case.public.buyer_ids
        )
        seller_ir = all(
            seller_receipts[seller]
            - (case.true_costs[seller] if seller in allocated_sellers else Decimal("0"))
            >= 0
            for seller in case.public.seller_ids
        )
        ir_holds = buyer_ir and seller_ir
        individual_rationality = MetricValue(bool(ir_holds))
        weak_budget_balance = MetricValue(bool(auctioneer_surplus >= 0))
    else:
        individual_rationality = MetricValue.na("missing_payments")
        weak_budget_balance = MetricValue.na("missing_payments")

    if "strategic_reports" not in spec.capabilities:
        deviation = MetricValue.na("strategic_reports_unsupported")
        profitable_count = MetricValue.na("strategic_reports_unsupported")
    elif method is None:
        deviation = MetricValue.na("missing_method_runner")
        profitable_count = MetricValue.na("missing_method_runner")
    elif set(case.public.buyer_ids) - set(case.true_values) or set(case.public.seller_ids) - set(case.true_costs):
        deviation = MetricValue.na("missing_true_types")
        profitable_count = MetricValue.na("missing_true_types")
    else:
        def actor_utility(actor: str, market_output: MarketOutcome) -> Decimal:
            market_pairs = _allocation_pairs(market_output)
            paid = sum(
                (payment.amount for payment in market_output.payments if payment.payer_id == actor),
                start=Decimal("0"),
            )
            received = sum(
                (payment.amount for payment in market_output.payments if payment.payee_id == actor),
                start=Decimal("0"),
            )
            if actor in case.true_values:
                allocated = any(buyer == actor for buyer, _ in market_pairs)
                return (case.true_values[actor] if allocated else Decimal("0")) - paid
            allocated = any(seller == actor for _, seller in market_pairs)
            return received - (case.true_costs[actor] if allocated else Decimal("0"))

        truthful_utilities = {
            actor: actor_utility(actor, output)
            for actor in (*case.public.buyer_ids, *case.public.seller_ids)
        }
        gains = []
        for (actor, _), public in bid_reports(case).items():
            alternative = method.clear(public, seed)
            gains.append(
                max(Decimal("0"), actor_utility(actor, alternative) - truthful_utilities[actor])
            )
        positive = [gain for gain in gains if gain > Decimal("1e-12")]
        deviation = MetricValue(float(max(gains, default=Decimal("0"))))
        profitable_count = MetricValue(len(positive))

    quantity_metric = (
        MetricValue(float(sum((allocation.quantity for allocation in output.allocations), Decimal("0"))))
        if "multi_unit" in spec.capabilities
        else MetricValue.na("single_unit_only")
    )
    oracle_pairs = _allocation_pairs(oracle_output) if oracle_output is not None else ()
    trade_count_loss = MetricValue(max(0, len(oracle_pairs) - len(pairs))) if oracle_output is not None else MetricValue.na("missing_oracle_output")
    efficient_trade_count = (
        MetricValue(len(oracle_pairs))
        if oracle_output is not None
        else MetricValue.na("missing_oracle_output")
    )
    normalized_trade_loss = (
        MetricValue(max(0, len(oracle_pairs) - len(pairs)) / len(oracle_pairs))
        if oracle_output is not None and oracle_pairs
        else MetricValue.na(
            "zero_efficient_trades" if oracle_output is not None else "missing_oracle_output"
        )
    )
    false_trade_count = MetricValue(
        sum(
            case.true_values[buyer] < case.true_costs[seller]
            for buyer, seller in pairs
            if buyer in case.true_values and seller in case.true_costs
        )
    ) if truth_complete else MetricValue.na("missing_true_types")
    seller_surplus_value = (
        sum(
            (
                seller_receipts[seller]
                - (case.true_costs[seller] if seller in allocated_sellers else Decimal("0"))
                for seller in case.public.seller_ids
            ),
            Decimal("0"),
        )
        if truth_complete and output.payments
        else None
    )
    matched_prices = [float(buyer_payments[buyer]) for buyer, _ in pairs]
    price_dispersion = (
        MetricValue(float(np.std(matched_prices)))
        if output.payments and matched_prices
        else MetricValue.na("missing_trade_prices")
    )
    participant_surplus_ratio = (
        MetricValue(float((buyer_surplus + seller_surplus_value) / oracle_gft))
        if buyer_surplus is not None
        and seller_surplus_value is not None
        and oracle_gft is not None
        and oracle_gft > 0
        else MetricValue.na("participant_surplus_or_oracle_unavailable")
    )

    return {
        "realized_gain_from_trade": MetricValue(float(realized)) if realized is not None else MetricValue.na("missing_true_types"),
        "gain_from_trade_ratio": ratio,
        "oracle_gain_from_trade": oracle_gft_metric,
        "allocation_efficiency": ratio,
        "trade_count": MetricValue(len(pairs)),
        "trade_count_loss": trade_count_loss,
        "normalized_trade_loss": normalized_trade_loss,
        "efficient_trade_count": efficient_trade_count,
        "participant_surplus_ratio": participant_surplus_ratio,
        "false_trade_count": false_trade_count,
        "seller_revenue": MetricValue(str(seller_revenue)) if output.payments else MetricValue.na("missing_payments"),
        "buyer_surplus": MetricValue(str(buyer_surplus)) if output.payments and buyer_surplus is not None else MetricValue.na("missing_payments" if not output.payments else "missing_true_types"),
        "auctioneer_surplus": MetricValue(str(auctioneer_surplus)) if output.payments else MetricValue.na("missing_payments"),
        "individual_rationality": individual_rationality,
        "weak_budget_balance": weak_budget_balance,
        "strong_budget_balance": strong_budget_balance,
        "seller_surplus_trading": (
            MetricValue(str(seller_surplus_value))
            if seller_surplus_value is not None
            else MetricValue.na("missing_payments" if not output.payments else "missing_true_types")
        ),
        "price_dispersion": price_dispersion,
        "quantity_weighted_trade_volume": quantity_metric,
        "max_deviation_gain": deviation,
        "trading_max_deviation_gain": deviation,
        "profitable_deviation_count": profitable_count,
    }


__all__ = [
    "MetricValue",
    "evaluate_procurement_metrics",
    "evaluate_trading_metrics",
    "evaluate_valuation_metrics",
]
