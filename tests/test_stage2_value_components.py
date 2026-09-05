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
    UTILITY_FUNCTIONS,
    VALUATORS,
    BanzhafValuator,
    ContributionRequest,
    ExactShapleyValuator,
    LearnedLinearValuator,
    MonteCarloShapleyValuator,
    SymbolicValuator,
    TabularTaskUtility,
    ValuationRequest,
    ValuationTarget,
    allocate_value_by_contribution,
)


def _request():
    product = DataProduct("p2", "value", DataReference("memory://p2", "records"), "owner", rights=RightsBundle(purposes=("valuation",)))
    task = TaskContext("t2", "maximize utility")
    units = tuple(ValuationTarget(item, product.product_id, DataScope.SAMPLE) for item in ("a", "b", "c"))
    return product, task, ContributionRequest(product, units, task)


def test_tabular_utility_and_registered_contribution_methods():
    product, task, request = _request()
    utility = TabularTaskUtility({"a": {"segment": "x", "label": 1, "fresh": 1.0}, "b": {"segment": "y", "label": 0, "fresh": 0.8}, "c": {"segment": "x", "label": 1, "fresh": 0.5}})
    context = RunContext("v2", seed=9)
    assert 0 < utility.score(product, ("a", "b"), task, context) <= 1
    exact = ExactShapleyValuator().value_contributions(request, utility, context)
    assert exact.converged is True and exact.utility_calls == 19
    mc = MonteCarloShapleyValuator().value_contributions(ContributionRequest(product, request.units, task, {"samples": 32, "seed": 3}), utility, context)
    assert mc.utility_calls == 1 + 32 * (len(request.units))
    banzhaf = BanzhafValuator().value_contributions(request, utility, context)
    assert len(banzhaf.contributions) == 3 and banzhaf.utility_calls == 24
    assert isinstance(UTILITY_FUNCTIONS.create("utility.tabular_task"), TabularTaskUtility)
    assert "missing" not in VALUATORS


def test_symbolic_and_learned_valuation_and_allocation():
    product, task, _ = _request()
    buyer = ActorProfile("buyer", ActorRole.BUYER, preferences={"value_multiplier": 1.1})
    request = ValuationRequest(product, (ValuationTarget("dataset", product.product_id, DataScope.DATASET),), buyer, task, product.rights, options={"evaluation_vector": {"quality": 0.8, "uniqueness": 0.9}})
    context = RunContext("v3")
    symbolic = SymbolicValuator("base_value * (0.7 * quality + 0.3 * uniqueness) * buyer_multiplier", base_value=100)
    assert symbolic.value(request, context).estimates[0].value == 91.3
    model = LearnedLinearValuator(("quality", "uniqueness"))
    requests = [request, ValuationRequest(product, request.targets, buyer, task, product.rights, options={"evaluation_vector": {"quality": 0.2, "uniqueness": 0.4}})]
    model.fit(requests, [80.0, 40.0], context)
    assert model.value(request, context).estimates[0].value > 0
    allocations = allocate_value_by_contribution(100, symbolic.value(request, context).estimates)
    assert allocations[0].unit == "monetary_allocation" and allocations[0].value == 100
    try:
        SymbolicValuator("__import__('os').system('echo bad')")
    except ValueError:
        pass
    else:
        raise AssertionError("unsafe expression was accepted")
