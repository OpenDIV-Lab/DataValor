from __future__ import annotations

from datamechbench.metrics import evaluate_valuation_market_metrics
from datamechbench.models import ValuationOutput
from datamechbench.settings.valuation_mechanisms import valuation_mechanism_settings


def _setting(mechanism: str):
    return next(
        item for item in valuation_mechanism_settings() if item.mechanism == mechanism
    )


def test_perfect_scores_have_zero_estimation_and_decision_regret() -> None:
    setting = _setting("budgeted_procurement")
    truth = {owner: float(index + 1) for index, owner in enumerate(setting.owner_ids)}
    oracle = ValuationOutput(truth, diagnostics={"runtime_seconds": 20.0})
    output = ValuationOutput(truth, diagnostics={"runtime_seconds": 3.0})
    metrics = evaluate_valuation_market_metrics(setting, output, oracle)
    assert metrics["score_ndcg"].value == 1.0
    assert metrics["normalized_score_mae"].value == 0.0
    assert metrics["max_score_error"].value == 0.0
    assert metrics["welfare_regret"].value == 0.0
    assert metrics["allocation_regret"].value == 0.0
    assert metrics["decision_flip_rate"].value == 0.0
    assert metrics["payment_mae"].value == 0.0
    assert metrics["valuation_budget_violation"].value is False
    assert metrics["valuation_ir_violation_count"].value == 0


def test_missing_oracle_is_na_and_never_numeric_zero() -> None:
    setting = _setting("top_k_acquisition")
    scores = {owner: 1.0 for owner in setting.owner_ids}
    metrics = evaluate_valuation_market_metrics(setting, ValuationOutput(scores), None)
    for metric_id in (
        "score_ndcg",
        "normalized_score_mae",
        "payment_mae",
        "welfare_regret",
        "decision_flip_rate",
    ):
        assert metrics[metric_id].applicable is False
        assert metrics[metric_id].value is None
        assert metrics[metric_id].reason == "missing_oracle_output"


def test_sequential_and_attack_metrics_are_explicitly_applicable() -> None:
    sequential = _setting("sequential_acquisition")
    truth = {owner: float(index + 1) for index, owner in enumerate(sequential.owner_ids)}
    reversed_scores = dict(zip(sequential.owner_ids, reversed(tuple(truth.values()))))
    metrics = evaluate_valuation_market_metrics(
        sequential,
        ValuationOutput(reversed_scores, diagnostics={"time_to_error": 7.0}),
        ValuationOutput(truth),
    )
    assert metrics["sequential_stopping_regret"].applicable
    assert metrics["time_to_error"].value == 7.0

    attack = _setting("replication_attack")
    attack_truth = {owner: float(index + 1) for index, owner in enumerate(attack.owner_ids)}
    attack_metrics = evaluate_valuation_market_metrics(
        attack, ValuationOutput(attack_truth), ValuationOutput(attack_truth)
    )
    assert attack_metrics["duplicate_spend"].applicable
    assert attack_metrics["noisy_spend"].applicable is False
