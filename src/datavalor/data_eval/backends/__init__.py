"""Optional DataEval backends.

The imports below are adapter-only imports; no external package is loaded until
an adapter method executes.
"""

from .cleanlab import CleanlabAdapter, CleanlabQualityMetric
from .evidently import EvidentlyAdapter, EvidentlyDriftMetric
from .great_expectations import (
    GreatExpectationsAdapter,
    GreatExpectationsMetric,
    GreatExpectationsPolicyEvaluator,
)
from .torchmetrics import TorchMetricAdapter, TorchMetricsAdapter

__all__ = [
    "CleanlabAdapter", "CleanlabQualityMetric", "EvidentlyAdapter", "EvidentlyDriftMetric",
    "GreatExpectationsAdapter", "GreatExpectationsMetric", "GreatExpectationsPolicyEvaluator",
    "TorchMetricAdapter", "TorchMetricsAdapter",
]
