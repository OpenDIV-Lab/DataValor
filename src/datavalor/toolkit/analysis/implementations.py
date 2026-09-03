"""DataValor Analyzer implementations backed by pure statistical helpers."""

from datavalor.core import ComponentSpec

from .interfaces import Analyzer, FrontierAnalyzer, ResultComparator
from .models import AnalysisResult, ComparisonResult
from .statistics import bootstrap_mean_interval, paired_difference, pareto_frontier


class BootstrapAnalyzer(Analyzer):
    @property
    def spec(self): return ComponentSpec("bootstrap", "1.0", "toolkit", "analyzer")
    def analyze(self, request, context):
        return AnalysisResult(self.spec.name, {metric: bootstrap_mean_interval(request.options.get(metric, []), seed=context.seed) for metric in request.metrics})


class PairedComparator(ResultComparator):
    @property
    def spec(self): return ComponentSpec("paired_comparison", "1.0", "toolkit", "result_comparator")
    def compare(self, request, context):
        base = request.options.get(request.baseline, []); return ComparisonResult(request.baseline, {candidate: paired_difference(base, request.options.get(candidate, [])) for candidate in request.candidates})


class ParetoFrontierAnalyzer(FrontierAnalyzer):
    @property
    def spec(self): return ComponentSpec("pareto_frontier", "1.0", "toolkit", "frontier_analyzer")
    def frontier(self, request, context): return AnalysisResult(self.spec.name, {"frontier": pareto_frontier(request.options.get("rows", []), request.metrics)})
