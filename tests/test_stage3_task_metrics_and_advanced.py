from __future__ import annotations

import pytest

from datavalor.core import (
    ActorProfile,
    ActorRole,
    DataProduct,
    DataReference,
    DataScope,
    RightsBundle,
    RunContext,
    TaskContext,
)
from datavalor.data_value import (
    ContributionRequest,
    GroupShapleyValuator,
    QualityAdjustedValuator,
    ScenarioValuator,
    TabularTaskUtility,
    ValuationRequest,
    ValuationTarget,
    binary_roc_auc,
    bootstrap_loo_values,
    classification_scores,
    incremental_gain,
    pairwise_interactions,
    ranking_scores,
    regression_scores,
)


def _product_task():
    product = DataProduct("p-metrics", "metrics", DataReference("memory://metrics", "records"), "owner", rights=RightsBundle(purposes=("valuation",)))
    task = TaskContext("t-metrics", "evaluate")
    return product, task


def test_task_metrics_cover_classification_regression_ranking_and_gain():
    classification = classification_scores([1, 0, 1, 0], [1, 1, 1, 0])
    assert classification["accuracy"] == 0.75 and classification["f1"] == pytest.approx(0.8)
    assert binary_roc_auc([1, 0, 1, 0], [0.9, 0.8, 0.7, 0.1]) == pytest.approx(0.75)
    regression = regression_scores([1, 2, 4], [1, 3, 2])
    assert regression["mae"] == pytest.approx(1.0) and regression["rmse"] > 0
    ranking = ranking_scores([3, 0, 2, 1], [0.9, 0.1, 0.8, 0.2], k=2)
    assert ranking["ndcg"] > 0.9 and ranking["k"] == 2
    assert incremental_gain(0.8, 0.9) == pytest.approx(0.1)
    assert incremental_gain(0.8, 0.6, direction="lower_is_better") == pytest.approx(0.2)


def test_group_interaction_bootstrap_and_scenario_valuation():
    product, task = _product_task()
    records = {"a": {"segment": "x", "label": 1, "fresh": 1.0}, "b": {"segment": "x", "label": 0, "fresh": 0.8}, "c": {"segment": "y", "label": 1, "fresh": 0.7}}
    utility = TabularTaskUtility(records)
    context = RunContext("advanced", seed=4)
    units = tuple(ValuationTarget(name, product.product_id, DataScope.SAMPLE) for name in records)
    grouped = GroupShapleyValuator().value_contributions(ContributionRequest(product, units, task, {"groups": {"x": ("a", "b"), "y": ("c",)}}), utility, context)
    assert {item.target_id for item in grouped.contributions} == {"x", "y"}
    interactions = pairwise_interactions(tuple(records), lambda selection, ctx: utility.score(product, selection, task, ctx), context=context)
    assert len(interactions) == 3 and interactions[0].unit == "utility_interaction"
    stability = bootstrap_loo_values(tuple(records), lambda selection, ctx: utility.score(product, selection, task, ctx), samples=16, seed=2, context=context)
    assert stability.contributions[0].uncertainty["lower_95"] <= stability.contributions[0].uncertainty["upper_95"]
    request = ValuationRequest(product, (ValuationTarget("dataset", product.product_id, DataScope.DATASET),), ActorProfile("buyer", ActorRole.BUYER, preferences={"value_multiplier": 1.1}), task, product.rights, options={"evaluation_vector": {"quality": 0.9, "uniqueness": 0.8, "freshness": 0.7}})
    quality = QualityAdjustedValuator(base_value=100).value(request, context)
    scenarios = ScenarioValuator({"low": {"quality": 0.5}, "high": {"quality": 1.0}}, base_value=100).value(request, context)
    assert quality.estimates[0].value > 0
    assert scenarios.diagnostics["lower_bound"] < scenarios.diagnostics["upper_bound"]
