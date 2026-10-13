from __future__ import annotations

import math

from datamechbench.metrics import evaluate_valuation_metrics
from datamechbench.models import ValuationOutput
from datamechbench.runner import build_registry
from datamechbench.settings.valuation import make_valuation_axiom_cases


def _case(property_name: str):
    return next(
        case for case in make_valuation_axiom_cases() if case.metadata["property"] == property_name
    )


def test_exact_shapley_satisfies_efficiency_dummy_and_symmetry() -> None:
    registry = build_registry()
    method = registry.create("shapley_exact")

    dummy_case = _case("dummy")
    dummy_output = method.evaluate(dummy_case, 0)
    dummy_metrics = evaluate_valuation_metrics(dummy_case, dummy_output)
    symmetric_case = _case("symmetric")
    symmetric_output = method.evaluate(symmetric_case, 0)
    symmetric_metrics = evaluate_valuation_metrics(symmetric_case, symmetric_output)

    assert dummy_metrics["efficiency_residual"].value == 0.0
    assert dummy_metrics["dummy_violation"].value == 0.0
    assert symmetric_metrics["symmetry_gap"].value == 0.0


def test_exact_least_core_reports_feasible_constraints_and_efficiency() -> None:
    case = _case("complementary")
    output = build_registry().create("least_core_exact").evaluate(case, 0)
    metrics = evaluate_valuation_metrics(case, output)

    assert math.isclose(metrics["efficiency_residual"].value, 0.0, abs_tol=1e-8)
    assert metrics["least_core_max_violation"].value <= 1e-8
    assert output.diagnostics["tie_break"] == "minimum_l2_norm"


def test_data_oob_uses_additive_owner_aggregation() -> None:
    from datamechbench.settings.valuation import make_valuation_corruption_cases

    case = make_valuation_corruption_cases(3)[0]
    output = build_registry().create("data_oob", {"n_estimators": 12}).evaluate(case, 3)

    assert output.diagnostics["owner_aggregation"] == "sum"
    assert set(output.scores) == set(case.owner_ids)


def test_influence_sign_is_documented_as_helpfulness() -> None:
    from datamechbench.settings.valuation import make_valuation_corruption_cases

    case = make_valuation_corruption_cases(4)[0]
    output = build_registry().create("influence_function").evaluate(case, 4)

    assert output.diagnostics["score_semantics"] == "positive_is_helpful"
    assert all(math.isfinite(value) for value in output.scores.values())


def test_ame_records_randomized_experiment_design() -> None:
    case = _case("additive")
    output = build_registry().create("ame", {"samples": 64}).evaluate(case, 11)

    assert output.diagnostics["regression"] == "lasso"
    assert output.diagnostics["design"] == "bernoulli_randomized_experiment"
    assert output.diagnostics["inclusion_probability"] == 0.5


def test_corruption_metrics_use_evaluator_only_labels() -> None:
    from datamechbench.settings.valuation import make_valuation_corruption_cases

    case = make_valuation_corruption_cases(9)[0]
    bad = set(case.metadata["corrupted_owners"])
    output = ValuationOutput(
        {owner: (-1.0 if owner in bad else 1.0) for owner in case.owner_ids}
    )

    metrics = evaluate_valuation_metrics(case, output)

    assert metrics["corruption_auroc"].value == 1.0
    assert metrics["corruption_auprc"].value == 1.0
    assert metrics["corruption_topk_f1"].value == 1.0

