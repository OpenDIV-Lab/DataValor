from __future__ import annotations

from decimal import Decimal

import pytest
from datamechbench.mechanism_bridge import bridge_valuation_scores
from datamechbench.settings.valuation_mechanisms import valuation_mechanism_settings


def test_every_primary_setting_has_broad_same_target_comparison() -> None:
    settings = valuation_mechanism_settings()
    assert {
        item.mechanism
        for item in settings
    } >= {
        "top_k_acquisition",
        "budgeted_procurement",
        "revenue_allocation",
        "reserve_admission",
        "corruption_exclusion",
        "replication_attack",
        "split_attack",
        "sequential_acquisition",
    }
    for setting in settings:
        applicable = [item for item in setting.methods if item.na_reason is None]
        same_target = [item for item in applicable if item.estimand == "ordinary_shapley"]
        assert len(applicable) >= 4
        if setting.primary:
            assert len(same_target) >= 4  # ELR plus at least three comparators.


def test_inapplicable_methods_have_structured_reasons() -> None:
    for setting in valuation_mechanism_settings():
        for method in setting.methods:
            if method.na_reason is not None:
                assert method.na_reason.code
                assert method.na_reason.detail


def test_bridge_uses_one_score_vector_without_method_specific_payments() -> None:
    setting = next(
        item
        for item in valuation_mechanism_settings()
        if item.mechanism == "budgeted_procurement"
    )
    scores = {owner: float(index + 1) for index, owner in enumerate(setting.owner_ids)}
    decision = bridge_valuation_scores(setting, scores)
    assert sum(decision.payments.values(), Decimal("0")) <= setting.budget
    assert set(decision.payments) == set(decision.selected_ids)
    assert all(decision.payments[owner] == setting.costs[owner] for owner in decision.selected_ids)
    with pytest.raises(ValueError, match="exactly match"):
        bridge_valuation_scores(setting, {"wrong": 1.0})


def test_revenue_allocation_conserves_declared_pool() -> None:
    setting = next(
        item
        for item in valuation_mechanism_settings()
        if item.mechanism == "revenue_allocation"
    )
    scores = {owner: float(index + 1) for index, owner in enumerate(setting.owner_ids)}
    decision = bridge_valuation_scores(setting, scores)
    assert sum(decision.payments.values(), Decimal("0")) == setting.budget
