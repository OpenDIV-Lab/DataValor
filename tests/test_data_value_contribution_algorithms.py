from __future__ import annotations

import importlib.metadata

import pytest

from datavalor.core import DataProduct, DataReference, RunContext, TaskContext
from datavalor.data_value import ContributionRequest, ValuationTarget, exact_shapley_values
from datavalor.data_value.backends.pydvl import PyDVLContributionValuator


def _request(options=None):
    product = DataProduct("p", "demo", DataReference("memory://demo", "records"), "owner")
    units = tuple(ValuationTarget(owner, "p", "owner") for owner in ("a", "b"))
    return ContributionRequest(product, units, TaskContext("t", "classification"), options or {})


def test_exact_shapley_is_efficient_and_calls_each_coalition_once():
    owners = tuple(f"o{index}" for index in range(6))
    weights = dict(zip(owners, (1, 2, 3, 4, 5, 6), strict=True))
    calls: list[frozenset[str]] = []

    def utility(coalition, _context):
        selected = frozenset(coalition)
        calls.append(selected)
        return float(sum(weights[owner] for owner in selected))

    report = exact_shapley_values(owners, utility)

    assert [item.value for item in report.contributions] == pytest.approx([1, 2, 3, 4, 5, 6])
    assert sum(item.value for item in report.contributions) == pytest.approx(
        utility(owners, None) - utility((), None)
    )
    assert report.utility_calls <= 2 ** len(owners)
    assert len(set(calls[:-2])) == report.utility_calls


def test_exact_shapley_rejects_duplicate_ids_and_oversized_games():
    def utility(coalition, context):
        del context
        return float(len(coalition))

    with pytest.raises(ValueError, match="unique"):
        exact_shapley_values(("a", "a"), utility)
    with pytest.raises(ValueError, match="max_records=1"):
        exact_shapley_values(("a", "b"), utility, max_records=1)


def test_pydvl_010_estimator_fits_dataset_and_maps_group_indices():
    marker_dataset = object()

    class FakeResult:
        values = (0.75, 0.25)
        indices = (1, 0)
        stderr = (0.02, 0.01)

    class FakeEstimator:
        result = None

        def __init__(self):
            self.fit_arguments = []

        def fit(self, dataset):
            self.fit_arguments.append(dataset)
            self.result = FakeResult()
            return self

    estimator = FakeEstimator()
    report = PyDVLContributionValuator(estimator=estimator).value_contributions(
        _request({"external_data": marker_dataset}),
        utility=lambda *args: 0.0,
        context=RunContext("pydvl-010"),
    )

    assert estimator.fit_arguments == [marker_dataset]
    assert [item.target_id for item in report.contributions] == ["b", "a"]
    assert [item.value for item in report.contributions] == [0.75, 0.25]
    assert [item.uncertainty["std_error"] for item in report.contributions] == [0.02, 0.01]


@pytest.mark.pydvl
def test_installed_pydvl_010_is_recognized():
    pytest.importorskip("pydvl", reason="optional_dependency_missing:pydvl")
    version = importlib.metadata.version("pydvl")
    if not version.startswith("0.10."):
        pytest.skip(f"unsupported_optional_version:pydvl=={version}")
    assert PyDVLContributionValuator().spec.requires
