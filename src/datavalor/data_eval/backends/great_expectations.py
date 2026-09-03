"""Great Expectations validation adapter.

Validation can be supplied as a callable for offline runs.  In a configured
environment the adapter looks for the lightweight ``great_expectations.validate``
entry point, then ``from_pandas``; this keeps version-specific GX contexts out
of DataValor's public API.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from datavalor.core import ComponentSpec, DataProduct, Evidence, RunContext, require_capability
from datavalor.data_gov.interfaces import PolicyEvaluator
from datavalor.data_gov.models import (
    GovernanceDecision,
    GovernanceFinding,
    GovernanceReport,
    Severity,
)

from ..interfaces import QualityMetric
from ..models import EvaluationRequest, MetricResult, ScoreDirection
from ._utils import as_mapping, records_for


def _success(result: Mapping[str, Any]) -> bool:
    value = result.get("success", result.get("successes"))
    if isinstance(value, bool):
        return value
    stats = result.get("statistics")
    if isinstance(stats, Mapping) and stats.get("evaluated_expectations"):
        return int(stats.get("successful_expectations", 0)) == int(stats["evaluated_expectations"])
    return False


class GreatExpectationsMetric(QualityMetric):
    """Run GX expectations and expose pass ratio plus failed-expectation evidence."""

    def __init__(self, expectations: Any = None, validator: Callable[..., Any] | None = None) -> None:
        self.expectations = expectations
        self.validator = validator

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("great_expectations.validation", "0.1.0", "data_eval", "quality_metric",
                             requires=("great-expectations>=0.18",), capabilities=("expectation", "checkpoint"))

    def _validate(self, rows: list[dict[str, Any]], request: EvaluationRequest) -> Mapping[str, Any]:
        fn = self.validator or request.options.get("validator")
        if fn is not None:
            try:
                return as_mapping(fn(rows, self.expectations))
            except TypeError:
                return as_mapping(fn(rows, expectations=self.expectations))
        gx = require_capability("great_expectations", "great_expectations", distribution="great-expectations", extra="quality")
        direct = getattr(gx, "validate", None)
        if callable(direct):
            return as_mapping(direct(rows, expectations=self.expectations))
        # GX's DataFrame API is intentionally reached only here.  A caller can
        # provide a DataFrame through options to avoid requiring pandas.
        data = request.options.get("data")
        if data is None:
            try:
                import pandas as pd
                data = pd.DataFrame(rows)
            except ImportError as exc:
                raise RuntimeError("Great Expectations adapter needs pandas or options['data']") from exc
        converter = getattr(gx, "from_pandas", None)
        if not callable(converter):
            raise RuntimeError("installed Great Expectations version has no supported validation entry point")
        validator_obj = converter(data)
        if isinstance(self.expectations, (list, tuple)):
            for expectation in self.expectations:
                if callable(expectation):
                    expectation(validator_obj)
        run = getattr(validator_obj, "validate", None)
        return as_mapping(run()) if callable(run) else as_mapping(validator_obj)

    def compute(self, product: DataProduct, request: EvaluationRequest, context: RunContext) -> MetricResult:
        result = self._validate(records_for(product, request.options), request)
        stats = result.get("statistics", {}) if isinstance(result.get("statistics"), Mapping) else {}
        evaluated = int(stats.get("evaluated_expectations", result.get("evaluated_expectations", 0)) or 0)
        successful = int(stats.get("successful_expectations", result.get("successful_expectations", 0)) or 0)
        if not evaluated and "success" in result:
            evaluated, successful = 1, int(bool(result["success"]))
        score = successful / evaluated if evaluated else (1.0 if _success(result) else 0.0)
        failed = result.get("results", result.get("expectations", ()))
        evidence = tuple(Evidence("great_expectations.expectation", summary=str(item))
                         for item in (failed if isinstance(failed, (list, tuple)) else ())
                         if isinstance(item, Mapping) and not bool(item.get("success", True)))
        return MetricResult("great_expectations.pass_rate", "data_quality", request.scope, score,
                            ScoreDirection.HIGHER_IS_BETTER, unit="ratio", target_id=product.product_id,
                            statistics={"evaluated_expectations": evaluated, "successful_expectations": successful},
                            evidence=evidence, diagnostics={"run_id": context.run_id, "backend": "great_expectations"})


class GreatExpectationsPolicyEvaluator(PolicyEvaluator):
    """Map GX validation to a DataGov ``GovernanceReport``."""

    def __init__(self, validator: Callable[..., Any] | None = None, expectations: Any = None) -> None:
        self.metric = GreatExpectationsMetric(expectations, validator)

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("great_expectations.policy", "0.1.0", "data_gov", "policy_evaluator",
                             requires=("great-expectations>=0.18",))

    def evaluate(self, product: DataProduct, operation: str, metadata: Any, context: RunContext) -> GovernanceReport:
        options = {"validator": self.metric.validator}
        if "records" in context.config:
            options["records"] = context.config["records"]
        request = EvaluationRequest(options=options)
        result = self.metric.compute(product, request, context)
        failed = result.statistics.get("evaluated_expectations", 0) != result.statistics.get("successful_expectations", 0)
        findings = tuple(GovernanceFinding("gx.expectation_failed", "validation", Severity.MEDIUM,
                                            "Great Expectations 检查未全部通过", evidence=result.evidence)
                         for _ in ([1] if failed else []))
        return GovernanceReport(product.product_id, GovernanceDecision.REVIEW if failed else GovernanceDecision.ALLOW,
                                 policies=(operation,), findings=findings,
                                 diagnostics={"backend": "great_expectations", "run_id": context.run_id})


GreatExpectationsAdapter = GreatExpectationsMetric

__all__ = ["GreatExpectationsMetric", "GreatExpectationsAdapter", "GreatExpectationsPolicyEvaluator"]
