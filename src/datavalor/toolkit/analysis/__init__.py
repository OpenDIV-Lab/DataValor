"""Statistical analysis and comparison of experiment artifacts."""

from .implementations import BootstrapAnalyzer, PairedComparator, ParetoFrontierAnalyzer
from .interfaces import Analyzer, FrontierAnalyzer, ResultComparator
from .models import AnalysisRequest, AnalysisResult, ComparisonRequest, ComparisonResult
from .registry import ANALYZERS, FRONTIER_ANALYZERS, RESULT_COMPARATORS
from .statistics import (
    bootstrap_mean_interval,
    paired_bootstrap_difference,
    paired_difference,
    pareto_frontier,
    regret_summary,
    scalarized_score,
)
from .value_chain import ValueRealizationAnalyzer

for _component, _registry in (
    (BootstrapAnalyzer(), ANALYZERS),
    (PairedComparator(), RESULT_COMPARATORS),
    (ParetoFrontierAnalyzer(), FRONTIER_ANALYZERS),
    (ValueRealizationAnalyzer(), ANALYZERS),
):
    if _component.spec.name not in _registry:
        _registry.register(_component.spec, type(_component))

__all__ = [
    "ANALYZERS",
    "FRONTIER_ANALYZERS",
    "RESULT_COMPARATORS",
    "AnalysisRequest",
    "AnalysisResult",
    "Analyzer",
    "ComparisonRequest",
    "ComparisonResult",
    "FrontierAnalyzer",
    "ResultComparator",
    "bootstrap_mean_interval",
    "paired_difference",
    "paired_bootstrap_difference",
    "pareto_frontier",
    "regret_summary",
    "scalarized_score",
    "BootstrapAnalyzer",
    "PairedComparator",
    "ParetoFrontierAnalyzer",
    "ValueRealizationAnalyzer",
]
