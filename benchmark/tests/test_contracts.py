from __future__ import annotations

import json
from dataclasses import fields
from decimal import Decimal

import pytest
from datamechbench.models import (
    BenchmarkResult,
    MethodSpec,
    ProcurementInput,
    TradeInput,
    ValuationCase,
    ValuationOutput,
)
from datamechbench.registry import MethodRegistry, validate_output


class ConstantValuator:
    def __init__(self, spec: MethodSpec, value: float = 1.0) -> None:
        self.spec = spec
        self.value = value

    def evaluate(self, case: ValuationCase, seed: int) -> ValuationOutput:
        del seed
        return ValuationOutput({owner_id: self.value for owner_id in case.owner_ids})


def valuation_spec(method_id: str = "constant", *, stochastic: bool = False) -> MethodSpec:
    return MethodSpec(
        method_id=method_id,
        track="valuation",
        role="method",
        source="test",
        version="1",
        stochastic=stochastic,
        capabilities=frozenset({"scores"}),
        supported_case_types=frozenset({"analytic"}),
    )


def valuation_case() -> ValuationCase:
    return ValuationCase("case", ("o1", "o2"), lambda owners: float(len(owners)), "analytic")


def test_registry_rejects_duplicate_method_ids_and_creates_registered_method():
    registry = MethodRegistry()
    spec = valuation_spec()
    registry.register(spec, lambda params: ConstantValuator(spec, float(params.get("value", 1))))

    method = registry.create("constant", {"value": 2})
    assert method.evaluate(valuation_case(), seed=3).scores == {"o1": 2.0, "o2": 2.0}
    assert [item.method_id for item in registry.specs("valuation")] == ["constant"]

    with pytest.raises(ValueError, match="already registered"):
        registry.register(spec, lambda params: ConstantValuator(spec))


def test_public_market_inputs_do_not_expose_true_types_or_attack_labels():
    procurement_fields = {item.name for item in fields(ProcurementInput)}
    trade_fields = {item.name for item in fields(TradeInput)}

    assert {"true_costs", "true_values", "attack_labels"}.isdisjoint(procurement_fields)
    assert {"true_costs", "true_values", "attack_labels"}.isdisjoint(trade_fields)


def test_duplicate_owner_ids_are_rejected():
    with pytest.raises(ValueError, match="owner IDs must be unique"):
        ValuationCase("bad", ("o1", "o1"), lambda owners: 0.0, "analytic")


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
def test_output_validation_rejects_nonfinite_scores(bad_value: float):
    case = valuation_case()
    output = ValuationOutput({"o1": bad_value, "o2": 1.0})

    with pytest.raises(ValueError, match="finite"):
        validate_output(valuation_spec(), case, output)


def test_output_validation_rejects_unknown_owner_id():
    case = valuation_case()
    output = ValuationOutput({"o1": 1.0, "unknown": 2.0})

    with pytest.raises(ValueError, match="unknown owner"):
        validate_output(valuation_spec(), case, output)


def test_deterministic_registered_method_is_seed_invariant():
    registry = MethodRegistry()
    spec = valuation_spec()
    registry.register(spec, lambda params: ConstantValuator(spec, float(params.get("value", 1))))
    method = registry.create("constant", {"value": 4})

    first = method.evaluate(valuation_case(), seed=1)
    second = method.evaluate(valuation_case(), seed=999)
    assert first == second


def test_specs_and_results_are_json_serializable():
    spec = valuation_spec()
    result = BenchmarkResult(
        run_id="run-1",
        track="valuation",
        method_id=spec.method_id,
        case_id="case",
        seed=0,
        status="completed",
        metrics={"mae": {"value": 0.0, "applicable": True, "reason": None}},
        runtime_seconds=0.1,
        metadata={"method_spec": spec.to_dict()},
    )

    encoded = json.dumps(result.to_dict(), sort_keys=True)
    assert '"schema_version": "1.1"' in encoded
    assert '"method_id": "constant"' in encoded


def test_procurement_input_validates_ids_and_decimal_boundaries():
    public = ProcurementInput(
        seller_ids=("s1", "s2"),
        reported_costs={"s1": Decimal("1"), "s2": Decimal("2")},
        budget=Decimal("2"),
        utility=lambda sellers: float(len(sellers)),
        seller_values={"s1": 1.0, "s2": 1.0},
    )
    assert public.budget == Decimal("2")

    with pytest.raises(ValueError, match="seller IDs must be unique"):
        ProcurementInput(
            seller_ids=("s1", "s1"),
            reported_costs={"s1": Decimal("1")},
            budget=Decimal("2"),
            utility=lambda sellers: 0.0,
        )
