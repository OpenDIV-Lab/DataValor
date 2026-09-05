from __future__ import annotations

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
    ExactShapleyValuator,
    LearnedLinearValuator,
    SymbolicValuator,
    TabularTaskUtility,
    ValuationRequest,
    ValuationTarget,
    allocate_value_by_contribution,
)


def test_symbolic_expression_is_safe_and_explainable():
    product = DataProduct("p3", "p", DataReference("memory://p3", "records"), "owner", rights=RightsBundle(purposes=("valuation",)))
    buyer = ActorProfile("b", ActorRole.BUYER, preferences={"value_multiplier": 1.2})
    request = ValuationRequest(product, (ValuationTarget("dataset", "p3", DataScope.DATASET),), buyer, TaskContext("t", "task"), options={"evaluation_vector": {"quality": 0.8, "uniqueness": 0.9}})
    result = SymbolicValuator("base_value * quality * buyer_multiplier", base_value=100).value(request, RunContext("r"))
    assert result.estimates[0].value == 96.0
    assert result.estimates[0].explanation["expression"]
    for expression in ("__import__('os')", "open('x')", "quality.foo"):
        try:
            SymbolicValuator(expression)
        except ValueError:
            pass
        else:
            raise AssertionError(expression)


def test_linear_fit_and_contribution_allocation():
    product = DataProduct("p3", "p", DataReference("memory://p3", "records"), "owner", rights=RightsBundle(purposes=("valuation",)))
    task = TaskContext("t", "task")
    buyer = ActorProfile("b", ActorRole.BUYER)
    target = (ValuationTarget("dataset", "p3", DataScope.DATASET),)
    requests = [ValuationRequest(product, target, buyer, task, options={"evaluation_vector": {"quality": 0.2}}), ValuationRequest(product, target, buyer, task, options={"evaluation_vector": {"quality": 0.8}})]
    model = LearnedLinearValuator(("quality",))
    training = model.fit(requests, [20.0, 80.0], RunContext("fit"))
    assert training.observations == 2 and model.value(requests[1], RunContext("value")).estimates[0].value > 50
    utility = TabularTaskUtility({"a": {"segment": "x", "label": 1, "fresh": 1.0}, "b": {"segment": "y", "label": 0, "fresh": 0.8}})
    units = tuple(ValuationTarget(name, "p3", DataScope.SAMPLE) for name in ("a", "b"))
    contribution = ExactShapleyValuator().value_contributions(ContributionRequest(product, units, task), utility, RunContext("c"))
    allocations = allocate_value_by_contribution(100, contribution.contributions)
    assert sum(item.value for item in allocations) == 100
