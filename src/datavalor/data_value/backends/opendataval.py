"""OpenDataVal benchmark/valuation adapter with a stable DataValor boundary."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable

from datavalor.core import ComponentSpec, RunContext, require_capability
from datavalor.toolkit.benchmark.interfaces import BenchmarkMetric
from datavalor.toolkit.benchmark.models import BenchmarkCase

from ..interfaces import DataValuator
from ..models import ValuationMode, ValuationReport, ValuationRequest, ValueEstimate

_METHOD_NAMES = {
    "ame": ("AME", "AMEEvaluator"),
    "dvrl": ("DVRL", "DVRLEvaluator"),
    "knn_shapley": ("KNNShapley", "KNNShapleyEvaluator"),
    "lava": ("LavaEvaluator", "LAVA"),
    "data_oob": ("DataOob", "DataOOB"),
}


def _resolve_evaluator(module: Any, method: str) -> Any:
    namespace = getattr(module, "dataval", module)
    if namespace is module:
        try:
            namespace = require_capability(
                "opendataval", "opendataval.dataval", distribution="opendataval", extra="valuation"
            )
        except Exception:
            namespace = module
    for name in _METHOD_NAMES.get(method.lower(), (method,)):
        candidate = getattr(namespace, name, None) or getattr(module, name, None)
        if candidate is not None:
            return candidate() if isinstance(candidate, type) else candidate
    generic = getattr(module, "DataEvaluator", None)
    if generic is not None:
        return generic(method=method)
    raise RuntimeError(f"installed OpenDataVal version has no evaluator for method {method!r}")


def _run_evaluator(evaluator: Any, *, request: ValuationRequest, method: str, context: RunContext) -> Any:
    """Support both callable and OpenDataVal's stateful evaluator protocol."""

    if callable(evaluator) and not hasattr(evaluator, "data_values"):
        return evaluator(request=request, method=method, context=context)
    options = request.options
    input_data = options.get("input_data")
    prepare = getattr(evaluator, "input_data", None)
    if callable(prepare) and input_data is not None:
        if isinstance(input_data, Mapping):
            prepare(**input_data)
        else:
            prepare(*input_data)
    train = getattr(evaluator, "train", None)
    if callable(train):
        train(**dict(options.get("train_kwargs", {})))
    values = getattr(evaluator, "data_values", None)
    if not callable(values):
        raise RuntimeError("OpenDataVal evaluator must be callable or expose data_values()")
    return values()


class OpenDataValBenchmarkMetric(BenchmarkMetric):
    def __init__(self, evaluator: Callable[..., Any] | None = None, *, method: str = "ame") -> None:
        self.evaluator, self.method = evaluator, method

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("opendataval.benchmark", "0.1.0", "toolkit.benchmark", "benchmark_metric",
                             capabilities=("AME", "DVRL", "KNN_Shapley", "LAVA", "Data_OOB"),
                             requires=("opendataval>=1.0",))

    def measure(self, case: BenchmarkCase, outputs: Mapping[str, Any], context: RunContext) -> Mapping[str, float | int | bool | None]:
        evaluator = self.evaluator
        if evaluator is None:
            odv = require_capability("opendataval", "opendataval", distribution="opendataval", extra="valuation")
            evaluator = getattr(odv, "evaluate", None)
            if not callable(evaluator):
                raise RuntimeError("benchmark metric requires an injected OpenDataVal evaluator")
        raw = evaluator(case=case, outputs=outputs, method=self.method, context=context)
        if isinstance(raw, Mapping):
            return {str(k): v for k, v in raw.items() if isinstance(v, (float, int, bool)) or v is None}
        try:
            return {self.method: float(raw)}
        except (TypeError, ValueError):
            return {self.method: None}


class OpenDataValValuator(DataValuator):
    def __init__(self, evaluator: Callable[..., Any] | None = None, *, method: str = "DVRL") -> None:
        self.evaluator, self.method = evaluator, method

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("opendataval.valuation", "0.1.0", "data_value", "valuator",
                             capabilities=("AME", "DVRL", "KNN_Shapley", "LAVA", "Data_OOB"),
                             requires=("opendataval>=1.0",))

    def value(self, request: ValuationRequest, context: RunContext) -> ValuationReport:
        evaluator = self.evaluator if self.evaluator is not None else request.options.get("evaluator")
        if evaluator is None:
            odv = require_capability("opendataval", "opendataval", distribution="opendataval", extra="valuation")
            evaluator = _resolve_evaluator(odv, self.method)
        raw = _run_evaluator(evaluator, request=request, method=self.method, context=context)
        if isinstance(raw, Mapping):
            pairs = raw.items()
        else:
            pairs = zip((target.target_id for target in request.targets), raw)
        estimates = tuple(ValueEstimate(str(target_id), float(value), "utility", diagnostics={"backend": "opendataval"})
                          for target_id, value in pairs)
        return ValuationReport(request.product.product_id, f"opendataval.{self.method}", ValuationMode.MODEL_DEPENDENT,
                               estimates, buyer_id=request.buyer.actor_id if request.buyer else None,
                               task_id=request.task.task_id if request.task else context.task_id,
                               diagnostics={"run_id": context.run_id})


OpenDataValAdapter = OpenDataValValuator

__all__ = ["OpenDataValBenchmarkMetric", "OpenDataValValuator", "OpenDataValAdapter"]
