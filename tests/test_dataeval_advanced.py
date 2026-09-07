import pytest

from datavalor.core import DataProduct, DataReference, RunContext
from datavalor.data_eval import (
    EvaluationRequest,
    EvaluationThresholdGate,
    GroupCompletenessParityMetric,
    LabelConflictMetric,
    NumericRangeComplianceMetric,
    TextReadabilityMetric,
)


def _product():
    return DataProduct("eval", "eval", DataReference("memory://eval", "json"), "owner")


def _request(rows):
    return EvaluationRequest(options={"records": rows})


def test_numeric_range_and_label_conflict():
    rows = [{"id": "a", "score": 0.2, "label": "x"}, {"id": "a", "score": 1.2, "label": "y"}, {"id": "b", "score": None, "label": "z"}]
    request = _request(rows)
    range_result = NumericRangeComplianceMetric("score", 0, 1).compute(_product(), request, RunContext("r"))
    assert range_result.value == pytest.approx(1 / 3)
    assert range_result.statistics["invalid_count"] == 2
    conflict = LabelConflictMetric().compute(_product(), request, RunContext("r"))
    assert conflict.statistics["conflict_count"] == 1
    assert conflict.value == 0.5


def test_group_completeness_parity_and_readability():
    rows = [{"group": "a", "value": 1, "text": "Short clear sentence."}, {"group": "a", "value": 2, "text": "Another sentence."}, {"group": "b", "value": None, "text": ""}]
    request = _request(rows)
    parity = GroupCompletenessParityMetric("group", ("value",)).compute(_product(), request, RunContext("r"))
    assert parity.value == 1.0
    readable = TextReadabilityMetric().compute(_product(), request, RunContext("r"))
    assert 0 <= readable.value <= 1
    assert readable.statistics["record_count"] == 3


def test_threshold_gate_respects_metric_direction():
    metric = NumericRangeComplianceMetric("score", 0, 1).compute(_product(), _request([{"score": 0.5}]), RunContext("r"))
    from datavalor.data_eval import EvaluationReport

    report = EvaluationReport("eval", (metric,))
    gate = EvaluationThresholdGate().evaluate(report, {metric.name: 1.1})
    assert gate["status"] == "failed"
    assert gate["failed"] == 1
