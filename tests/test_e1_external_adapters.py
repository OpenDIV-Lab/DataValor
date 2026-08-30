"""Offline contract tests for E1 adapters (external packages are mocked/injected)."""

from datavalor.core import DataProduct, DataReference, RunContext
from datavalor.data_eval import EvaluationRequest
from datavalor.data_eval.backends.cleanlab import CleanlabQualityMetric
from datavalor.data_eval.backends.evidently import EvidentlyDriftMetric
from datavalor.data_eval.backends.great_expectations import GreatExpectationsMetric
from datavalor.data_eval.backends.torchmetrics import TorchMetricsAdapter
from datavalor.data_prof import ProfileRequest
from datavalor.data_prof.backends.fg_profile import FgDataProfiler


def product():
    return DataProduct("p1", "demo", DataReference("memory://demo", "records"), "owner")


def context():
    return RunContext("run-e1")


def test_cleanlab_injected_detector_maps_issues_to_evidence():
    def detector(rows, **kwargs):
        return [{"is_label_issue": True, "label_score": 0.1}, {"is_label_issue": False}]

    result = CleanlabQualityMetric(detector=detector).compute(
        product(), EvaluationRequest(options={"records": [{"label": 0}, {"label": 1}]}), context()
    )
    assert result.name == "cleanlab.label_issue_rate"
    assert result.value == 0.5
    assert result.statistics["issue_count"] == 1
    assert result.evidence[0].kind == "cleanlab.issue"


def test_gx_callable_supports_mapping_validation_result():
    result = GreatExpectationsMetric(
        expectations=["x"], validator=lambda rows, expectations: {
            "success": False,
            "statistics": {"evaluated_expectations": 2, "successful_expectations": 1},
            "results": [{"success": False, "expectation_type": "expect_column_values_to_not_be_null"}],
        }
    ).compute(product(), EvaluationRequest(options={"records": [{"x": 1}]}), context())
    assert result.value == 0.5
    assert len(result.evidence) == 1


def test_evidently_runner_and_profile_builder_are_dependency_free():
    drift = EvidentlyDriftMetric(runner=lambda current, reference: {"drift_share": 0.25}).compute(
        product(), EvaluationRequest(options={"records": [{"x": 1}], "reference_records": [{"x": 0}]}), context()
    )
    assert drift.value == 0.75

    profile = FgDataProfiler(builder=lambda rows, request: {
        "variables": {"x": {"type": "Numeric", "count": 1, "n_missing": 0, "n_unique": 1, "mean": 1}}
    }).profile(product(), ProfileRequest(options={"records": [{"x": 1}]}), context())
    assert profile.fields[0].name == "x"
    assert profile.fields[0].statistics["mean"] == 1


def test_torchmetrics_lifecycle_is_bridged():
    class FakeMetric:
        def update(self, targets, predictions):
            self.seen = (targets, predictions)

        def compute(self):
            return 0.8

    result = TorchMetricsAdapter(metric=FakeMetric(), name="accuracy").compute(
        product(), EvaluationRequest(options={"records": [{"target": 1, "prediction": 1}]}), context()
    )
    assert result.name == "accuracy"
    assert result.value == 0.8
