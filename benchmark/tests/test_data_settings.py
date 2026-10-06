from __future__ import annotations

import math
from decimal import Decimal

import numpy as np
from datamechbench.data import (
    BUYER_MULTIPLIERS,
    SELLER_MULTIPLIERS,
    load_owner_dataset,
    make_analytic_valuation_cases,
    make_procurement_cases,
    make_real_valuation_cases,
    make_trade_cases,
)


def _by_id(cases):
    return {case.case_id: case for case in cases}


def test_analytic_games_encode_additivity_duplication_and_complementarity():
    cases = _by_id(make_analytic_valuation_cases())

    additive = cases["C-add"]
    assert [additive.utility((owner,)) for owner in additive.owner_ids] == [
        1.0,
        2.0,
        3.0,
        4.0,
        5.0,
        6.0,
    ]

    duplicate = cases["C-dup"]
    assert duplicate.utility(("o0",)) == duplicate.utility(("o1",))
    assert duplicate.utility(("o0", "o1")) == duplicate.utility(("o0",))

    complementary = cases["C-comp"]
    ordinary_sum = complementary.utility(("o2",)) + complementary.utility(("o3",))
    assert complementary.utility(("o2", "o3")) == ordinary_sum + 10.0
    assert complementary.utility(("o1", "o2")) == 5.0


def test_owner_dataset_has_reproducible_stratified_disjoint_split():
    first = load_owner_dataset(seed=42)
    second = load_owner_dataset(seed=42)

    assert first.source_shape == (569, 30)
    assert (len(first.train_indices), len(first.validation_indices), len(first.test_indices)) == (
        341,
        114,
        114,
    )
    assert np.array_equal(first.train_indices, second.train_indices)
    assert np.array_equal(first.validation_indices, second.validation_indices)
    assert np.array_equal(first.test_indices, second.test_indices)

    split_sets = [
        set(first.train_indices),
        set(first.validation_indices),
        set(first.test_indices),
    ]
    assert split_sets[0].isdisjoint(split_sets[1])
    assert split_sets[0].isdisjoint(split_sets[2])
    assert split_sets[1].isdisjoint(split_sets[2])
    assert set.union(*split_sets) == set(range(569))

    owner_rows = [set(rows) for rows in first.owner_rows.values()]
    assert len(owner_rows) == 8
    assert set.union(*owner_rows) == set(range(len(first.x_train)))
    for position, rows in enumerate(owner_rows):
        for other in owner_rows[position + 1 :]:
            assert rows.isdisjoint(other)
    for rows in owner_rows:
        labels = set(first.y_train[list(rows)])
        assert labels == {0, 1}


def test_real_cases_copy_rows_exactly_and_flip_exactly_forty_percent():
    cases = _by_id(make_real_valuation_cases(seed=42))
    assert set(cases) == {
        "C-real-clean",
        "C-real-dup",
        "C-real-noise",
        "C-real-wine-clean",
        "C-real-digits-clean",
        "C-real-size-skew",
    }

    clean = cases["C-real-clean"].metadata["owner_dataset"]
    duplicate = cases["C-real-dup"].metadata["owner_dataset"]
    source_rows = clean.owner_rows["o0"]
    copied_rows = duplicate.owner_rows["o8"]
    assert np.array_equal(duplicate.x_train[list(copied_rows)], clean.x_train[list(source_rows)])
    assert np.array_equal(duplicate.y_train[list(copied_rows)], clean.y_train[list(source_rows)])

    noisy = cases["C-real-noise"].metadata["owner_dataset"]
    noisy_rows = noisy.owner_rows["o7"]
    changed = np.count_nonzero(clean.y_train[list(noisy_rows)] != noisy.y_train[list(noisy_rows)])
    assert changed == round(0.4 * len(noisy_rows))
    assert noisy.noise_rates["o7"] == 0.4
    assert cases["C-real-noise"].metadata["bad_owner"] == "o7"

    assert cases["C-real-wine-clean"].metadata["owner_dataset"].dataset_id == "sklearn-wine"
    assert cases["C-real-digits-clean"].metadata["owner_dataset"].dataset_id == "sklearn-digits"


def test_empty_and_one_class_coalitions_use_finite_baseline():
    clean_case = _by_id(make_real_valuation_cases(seed=42))["C-real-clean"]
    empty = clean_case.utility(())
    one_class_rows = np.flatnonzero(
        clean_case.metadata["owner_dataset"].y_train == 0
    )[:8]
    one_class = clean_case.metadata["owner_dataset"].utility_for_rows(one_class_rows)

    assert math.isfinite(empty)
    assert math.isfinite(one_class)
    assert 0.0 <= empty <= 1.0
    assert 0.0 <= one_class <= 1.0


def test_procurement_cases_hide_true_costs_and_use_declared_cost_formula():
    cases = make_procurement_cases(seed=42)
    real_noise = next(
        case
        for case in cases
        if case.metadata["source_case_id"] == "C-real-noise"
        and case.metadata["budget_ratio"] == 0.5
    )
    dataset = real_noise.metadata["owner_dataset"]

    for seller in real_noise.public.seller_ids:
        expected = Decimal(str(10 + 0.05 * len(dataset.owner_rows[seller]) + 20 * dataset.noise_rates[seller]))
        assert real_noise.true_costs[seller] == expected
        assert real_noise.public.reported_costs[seller] == expected
    assert real_noise.public.budget == sum(real_noise.true_costs.values(), Decimal("0")) * Decimal("0.5")
    assert not hasattr(real_noise.public, "true_costs")


def test_trade_cases_use_fixed_data_utility_calibration_arrays():
    assert BUYER_MULTIPLIERS == (0.55, 0.65, 0.75, 0.85, 0.95, 1.05, 1.15, 1.25, 1.35, 1.45)
    assert SELLER_MULTIPLIERS == (0.20, 0.28, 0.36, 0.44, 0.52, 0.60, 0.68, 0.76, 0.84, 0.92)

    cases = _by_id(make_trade_cases(seed=42))
    single = cases["S5-single-sale"]
    double = cases["S6-double-auction"]
    assert len(single.public.buyer_ids) == 10
    assert len(single.public.seller_ids) == 1
    assert single.public.posted_price is not None
    assert single.public.bids == single.true_values
    assert single.public.asks == single.true_costs
    assert len(double.public.buyer_ids) == 10
    assert len(double.public.seller_ids) == 10
    assert double.public.bids == double.true_values
    assert double.public.asks == double.true_costs
    assert Decimal("0") < double.metadata["base_value"]
