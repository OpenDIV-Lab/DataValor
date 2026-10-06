import pytest

from datavalor.data_price import fit_monotone_acceptance, select_revenue_price


def test_monotone_acceptance_pools_weighted_upward_violations():
    fitted = fit_monotone_acceptance(
        prices=(1.0, 1.0, 2.0, 3.0),
        accepted=(1, 1, 0, 1),
        price_grid=(0.5, 1.0, 2.0, 3.0, 4.0),
    )

    assert fitted == pytest.approx((1.0, 1.0, 0.5, 0.5, 0.5))


def test_monotone_acceptance_is_bounded_and_nonincreasing():
    fitted = fit_monotone_acceptance(
        prices=(10.0, 20.0, 30.0, 40.0),
        accepted=(1, 0, 1, 0),
        price_grid=(10.0, 15.0, 20.0, 30.0, 40.0),
    )

    assert all(0 <= value <= 1 for value in fitted)
    assert all(left >= right for left, right in zip(fitted, fitted[1:]))


def test_monotone_acceptance_rejects_invalid_observations():
    with pytest.raises(ValueError, match="matching"):
        fit_monotone_acceptance((1.0,), (1, 0), (1.0,))
    with pytest.raises(ValueError, match="binary"):
        fit_monotone_acceptance((1.0,), (2,), (1.0,))
    with pytest.raises(ValueError, match="finite"):
        fit_monotone_acceptance((float("nan"),), (1,), (1.0,))


def test_revenue_selector_returns_lowest_maximizing_price():
    selected = select_revenue_price(
        prices=(3.0, 1.0, 2.0),
        acceptance=(0.5, 1.0, 0.75),
    )

    assert selected == 2.0


def test_revenue_selector_rejects_invalid_probabilities():
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        select_revenue_price((1.0, 2.0), (1.1, 0.5))
