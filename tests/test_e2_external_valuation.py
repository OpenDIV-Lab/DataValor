"""Offline tests for E2 valuation and benchmark adapters."""

from datavalor.core import ArtifactRef, DataProduct, DataReference, RunContext, TaskContext
from datavalor.data_value import (
    ContributionRequest,
    ValuationRequest,
    ValuationTarget,
)
from datavalor.data_value.backends.opendataval import (
    OpenDataValBenchmarkMetric,
    OpenDataValValuator,
)
from datavalor.data_value.backends.pydvl import PyDVLContributionValuator, PyDVLValuator
from datavalor.toolkit.benchmark import BenchmarkCase
from datavalor.toolkit.benchmark.backends.wilds import WILDSDataProvider


def product():
    return DataProduct("p1", "demo", DataReference("memory://demo", "records"), "owner")


def targets():
    return (
        ValuationTarget("a", "p1", "sample"),
        ValuationTarget("b", "p1", "sample"),
    )


def test_pydvl_contribution_callable_maps_vector():
    request = ContributionRequest(product(), targets(), TaskContext("t", "classify"))
    report = PyDVLContributionValuator(runner=lambda **kwargs: {"a": 0.3, "b": 0.7}).value_contributions(
        request, utility=lambda *args: 1.0, context=RunContext("e2")
    )
    assert report.method == "pydvl.shapley"
    assert [item.value for item in report.contributions] == [0.3, 0.7]


def test_pydvl_and_opendataval_target_reports():
    request = ValuationRequest(product(), targets(), options={})
    pydvl = PyDVLValuator(runner=lambda **kwargs: [1.0, 2.0]).value(request, RunContext("e2"))
    assert [item.value for item in pydvl.estimates] == [1.0, 2.0]
    odv = OpenDataValValuator(evaluator=lambda **kwargs: {"a": 4.0, "b": 5.0}).value(request, RunContext("e2"))
    assert odv.estimates[1].value == 5.0


def test_opendataval_benchmark_and_wilds_provider_injection():
    case = BenchmarkCase("c1", {"in": ArtifactRef("i", "input", "v1")}, parameters={"dataset": "demo", "split": "train"})
    metric = OpenDataValBenchmarkMetric(evaluator=lambda **kwargs: {"utility": 0.9})
    assert metric.measure(case, {}, RunContext("e2"))["utility"] == 0.9

    class FakeDataset:
        def get_subset(self, split):
            return {"split": split, "rows": [1, 2]}

    loaded = WILDSDataProvider(loader=lambda **kwargs: FakeDataset()).load(case, RunContext("e2"))
    assert loaded["dataset"].payload["split"] == "train"
    assert loaded["dataset"].diagnostics["official_split"] is True
