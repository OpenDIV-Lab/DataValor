"""pyDVL contribution/valuation adapter.

pyDVL has evolved from function-based estimators to estimator classes.  This
adapter intentionally accepts an injected callable/estimator and uses a small
name-based resolver for installed versions, while always returning DataValor
``ValueEstimate`` and ``ContributionReport`` objects.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable

from datavalor.core import ComponentSpec, RunContext, require_capability

from ..interfaces import ContributionValuator, DataValuator, UtilityFunction
from ..models import (
    ContributionReport,
    ContributionRequest,
    ValuationMode,
    ValuationReport,
    ValuationRequest,
    ValueEstimate,
)


def _number(value: Any) -> float:
    try:
        return float(value.item())
    except AttributeError:
        return float(value)


def _estimates(raw: Any, ids: tuple[str, ...], backend: str = "pydvl") -> tuple[ValueEstimate, ...]:
    if isinstance(raw, Mapping):
        return tuple(ValueEstimate(str(key), _number(value), "utility", diagnostics={"backend": backend})
                     for key, value in raw.items())
    values = raw.values if hasattr(raw, "values") else raw
    if callable(values):
        values = values()
    values = list(values)
    indices = getattr(raw, "indices", ids)
    indices = list(indices() if callable(indices) else indices)
    stderr = getattr(raw, "stderr", getattr(raw, "standard_errors", None))
    stderr = list(stderr() if callable(stderr) else stderr) if stderr is not None else []
    return tuple(
        ValueEstimate(
            str(indices[i] if i < len(indices) else ids[i] if i < len(ids) else i),
            _number(value),
            "utility",
            uncertainty={"std_error": _number(stderr[i])} if i < len(stderr) else {},
            diagnostics={"backend": backend, "external_index": i},
        )
        for i, value in enumerate(values)
    )


class PyDVLContributionValuator(ContributionValuator):
    def __init__(self, estimator: Any = None, *, method: str = "shapley", runner: Callable[..., Any] | None = None) -> None:
        self.estimator, self.method, self.runner = estimator, method, runner

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("pydvl.contribution", "0.1.0", "data_value", "contribution_valuator",
                             capabilities=("shapley", "semivalue", "influence"), requires=("pydvl>=0.9",))

    def _run(self, request: ContributionRequest, utility: UtilityFunction, context: RunContext) -> Any:
        ids = tuple(unit.target_id for unit in request.units)
        options = dict(request.method_options)
        runner = self.runner or options.pop("runner", None)
        if runner is not None:
            return runner(ids=ids, utility=utility, request=request, context=context, **options)
        if self.estimator is not None:
            estimator = self.estimator
        else:
            pydvl = require_capability("pydvl", "pydvl", distribution="pydvl", extra="valuation")
            valuation = getattr(pydvl, "valuation", pydvl)
            estimator = None
            for name in ("compute_shapley_values", "shapley", "ShapleyValuation", "compute_semivalues"):
                candidate = getattr(valuation, name, None)
                if candidate is not None:
                    estimator = candidate() if isinstance(candidate, type) else candidate
                    break
            if estimator is None:
                raise RuntimeError("installed pyDVL version exposes no supported valuation entry point")
        fit = getattr(estimator, "fit", None)
        if callable(fit):
            external_data = options.pop("external_data", ids)
            external_utility = options.pop("external_utility", utility)
            fitted = fit(external_data, external_utility, **options)
            result = fitted if fitted is not None else estimator
            for attribute in ("result", "values"):
                value = getattr(result, attribute, None)
                if value is not None:
                    return value() if callable(value) else value
            return result
        value_attr = getattr(estimator, "value", None)
        if value_attr is not None and not callable(value_attr):
            return value_attr
        fn = value_attr if callable(value_attr) else estimator
        if not callable(fn):
            values = getattr(estimator, "values", None)
            if values is not None:
                return values() if callable(values) else values
            raise TypeError("pyDVL estimator must be callable or expose value/values")
        try:
            return fn(ids, utility, **options)
        except TypeError:
            return fn(data=ids, utility=utility, **options)

    def value_contributions(self, request: ContributionRequest, utility: UtilityFunction, context: RunContext) -> ContributionReport:
        ids = tuple(unit.target_id for unit in request.units)
        raw = self._run(request, utility, context)
        estimates = _estimates(raw, ids)
        return ContributionReport(request.product.product_id, f"pydvl.{self.method}", estimates,
                                  utility_calls=None, converged=True,
                                  diagnostics={"run_id": context.run_id, "method": self.method})


class PyDVLValuator(DataValuator):
    """Wrap a pyDVL value function for target-level DataValor reports."""

    def __init__(self, runner: Callable[..., Any] | None = None, *, method: str = "influence") -> None:
        self.runner, self.method = runner, method

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("pydvl.valuation", "0.1.0", "data_value", "valuator",
                             capabilities=("influence",), requires=("pydvl>=0.9",))

    def value(self, request: ValuationRequest, context: RunContext) -> ValuationReport:
        ids = tuple(target.target_id for target in request.targets)
        runner = self.runner or request.options.get("runner")
        if runner is None:
            require_capability("pydvl", "pydvl", distribution="pydvl", extra="valuation")
            raise RuntimeError("provide a pyDVL estimator runner compatible with this DataValor adapter")
        raw = runner(request=request, context=context)
        estimates = _estimates(raw, ids)
        return ValuationReport(request.product.product_id, f"pydvl.{self.method}", ValuationMode.MODEL_DEPENDENT,
                               estimates, buyer_id=request.buyer.actor_id if request.buyer else None,
                               task_id=request.task.task_id if request.task else context.task_id,
                               diagnostics={"run_id": context.run_id})


__all__ = ["PyDVLContributionValuator", "PyDVLValuator"]
