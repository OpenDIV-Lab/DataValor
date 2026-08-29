"""Statistical analysis and comparison of experiment artifacts."""

from .implementations import BootstrapAnalyzer, PairedComparator, ParetoFrontierAnalyzer
from .interfaces import Analyzer, FrontierAnalyzer, ResultComparator
from .models import AnalysisRequest, AnalysisResult, ComparisonRequest, ComparisonResult
from .registry import ANALYZERS, FRONTIER_ANALYZERS, RESULT_COMPARATORS
from .statistics import bootstrap_mean_interval, paired_difference, pareto_frontier

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
    "pareto_frontier",
    "BootstrapAnalyzer",
    "PairedComparator",
    "ParetoFrontierAnalyzer",
]
