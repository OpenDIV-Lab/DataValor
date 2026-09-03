"""Evidently drift/test adapter with report snapshots kept as evidence."""

from __future__ import annotations

from typing import Any, Callable, Mapping

from datavalor.core import ComponentSpec, DataProduct, Evidence, RunContext, require_capability

from ..interfaces import QualityMetric
from ..models import EvaluationRequest, MetricResult, ScoreDirection
from ._utils import as_mapping, first_number, records_for


def _find_metric(mapping: Mapping[str, Any], names: tuple[str, ...]) -> Any:
    """Find a metric key in either legacy or current Evidently snapshots."""

    for key, value in mapping.items():
        if str(key).lower() in names:
            return value
        if isinstance(value, Mapping):
            found = _find_metric(value, names)
            if found is not None:
                return found
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, Mapping):
                    found = _find_metric(item, names)
                    if found is not None:
                        return found
    return None


class EvidentlyDriftMetric(QualityMetric):
    def __init__(self, reference: list[dict[str, Any]] | None = None, runner: Callable[..., Any] | None = None) -> None:
        self.reference, self.runner = reference, runner

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("evidently.drift", "0.1.0", "data_eval", "quality_metric",
                             requires=("evidently>=0.4",), capabilities=("drift", "report_snapshot"))

    def _run(self, current: list[dict[str, Any]], reference: Any, request: EvaluationRequest) -> Mapping[str, Any]:
        fn = self.runner or request.options.get("runner")
        if fn is not None:
            return as_mapping(fn(current, reference))
        ev = require_capability("evidently", "evidently", distribution="evidently", extra="quality")
        report_cls = getattr(ev, "Report", None)
        if report_cls is None:
            raise RuntimeError("installed Evidently version has no Report API")
        report = report_cls(metrics=request.options.get("metrics", []))
        run = getattr(report, "run", None)
        if not callable(run):
            raise RuntimeError("Evidently Report object has no run method")
        current_data, reference_data = current, reference
        # Evidently's documented input is pandas DataFrame.  Conversion is
        # deferred and best-effort so lightweight test doubles can still use
        # plain record lists.
        try:
            pandas = require_capability("pandas", "pandas", distribution="pandas", extra="quality")
            current_data = pandas.DataFrame(current)
            reference_data = pandas.DataFrame(reference)
        except Exception:
            pass
        return as_mapping(run(current_data=current_data, reference_data=reference_data))

    def compute(self, product: DataProduct, request: EvaluationRequest, context: RunContext) -> MetricResult:
        current = records_for(product, request.options)
        reference = self.reference if self.reference is not None else request.options.get("reference_records", [])
        result = self._run(current, reference, request)
        metrics = result.get("metrics", result)
        drift = result.get("drift_share", result.get("share_of_drifted_columns"))
        if drift is None and isinstance(metrics, Mapping):
            drift = _find_metric(metrics, ("drift_share", "share_of_drifted_columns"))
        if isinstance(drift, Mapping):
            drift = drift.get("value", drift.get("current", drift.get("share")))
        drift_value = first_number(drift) or 0.0
        return MetricResult("evidently.drift_free_rate", "distribution_drift", request.scope,
                            max(0.0, min(1.0, 1.0 - drift_value)), ScoreDirection.HIGHER_IS_BETTER,
                            unit="ratio", target_id=product.product_id,
                            statistics={"drift_share": drift_value, "reference_count": len(reference), "current_count": len(current)},
                            evidence=(Evidence("evidently.report", summary="Evidently drift report", metadata=dict(result)),),
                            diagnostics={"backend": "evidently", "run_id": context.run_id})


EvidentlyAdapter = EvidentlyDriftMetric

__all__ = ["EvidentlyDriftMetric", "EvidentlyAdapter"]
