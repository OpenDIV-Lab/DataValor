from datavalor.core import (
    ActorProfile,
    ActorRole,
    DataProduct,
    DataReference,
    DataScope,
    RunContext,
    TaskContext,
)
from datavalor.data_eval import EvaluationRequest, LexicalDiversityMetric
from datavalor.data_value import (
    ContributionRequest,
    LeaveOneOutValuator,
    ValuationRequest,
    ValuationTarget,
    WeightedUserTaskValuator,
    exact_shapley_values,
    load_requirements,
)


def _product():
    return DataProduct("p", "demo", DataReference("memory://p", "jsonl"), "owner")


def test_lexical_metric_uses_datavalor_result_contract():
    product = _product(); context = RunContext("r1")
    result = LexicalDiversityMetric().compute(product, EvaluationRequest(options={"records": [{"text": "a b a"}]}), context)
    assert result.name == "text.lexical_diversity"
    assert result.scope is DataScope.DATASET
    assert 0 <= result.value <= 1


def test_contribution_and_weighted_valuation_are_separate():
    product = _product(); task = TaskContext("t", "maximize", metadata={"metric_weights": {"quality": 1}})
    units = tuple(ValuationTarget(str(i), "p", DataScope.SAMPLE) for i in range(3))
    class Utility:
        def score(self, _product, selection, _task, _context):
            return float(len(selection))

    utility = Utility()
    report = LeaveOneOutValuator().value_contributions(ContributionRequest(product, units, task), utility, RunContext("r"))
    assert len(report.contributions) == 3 and report.method == "leave_one_out"
    valuation = WeightedUserTaskValuator(base_value=100).value(
        ValuationRequest(product, units, ActorProfile("b", ActorRole.BUYER), task, options={"evaluation_vector": {"quality": .8}}), RunContext("r")
    )
    assert valuation.estimates[0].currency == "CNY"


def test_exact_shapley_and_requirements(tmp_path):
    report = exact_shapley_values(("a", "b"), lambda selection, _ctx: float(len(selection) ** 2))
    assert [item.value for item in report.contributions] == [2.0, 2.0]
    path = tmp_path / "requirements.json"
    path.write_text('{"record_type":"task","task_id":"t1"}', encoding="utf-8")
    assert load_requirements(path)["tasks"][0]["task_id"] == "t1"
