"""DataValor Analyzer implementations backed by pure statistical helpers."""

from datavalor.core import ComponentSpec

from .interfaces import Analyzer, FrontierAnalyzer, ResultComparator
from .models import AnalysisResult, ComparisonResult
from .statistics import (
    bootstrap_mean_interval,
    paired_bootstrap_difference,
    pareto_frontier,
    scalarized_score,
)


class BootstrapAnalyzer(Analyzer):
    @property
    def spec(self): return ComponentSpec("bootstrap", "1.0", "toolkit", "analyzer")
    def analyze(self, request, context):
        statistics = {
            metric: bootstrap_mean_interval(
                request.options.get(metric, []),
                confidence=float(request.options.get("confidence", 0.95)),
                samples=int(request.options.get("samples", 2000)),
                seed=context.seed,
            )
            for metric in request.metrics
        }
        return AnalysisResult(
            self.spec.name,
            statistics,
            warnings=tuple(
                f"metric {metric} has no finite observations"
                for metric, value in statistics.items()
                if value is None
            ),
            diagnostics={"seed": context.seed, "method": "iid_bootstrap_mean"},
        )


class PairedComparator(ResultComparator):
    @property
    def spec(self): return ComponentSpec("paired_comparison", "1.0", "toolkit", "result_comparator")
    def compare(self, request, context):
        base = request.options.get(request.baseline, [])
        comparisons = {}
        for candidate in request.candidates:
            values = request.options.get(candidate, [])
            comparisons[candidate] = paired_bootstrap_difference(
                base,
                values,
                confidence=float(request.options.get("confidence", 0.95)),
                samples=int(request.options.get("samples", 2000)),
                seed=context.seed,
            )
        return ComparisonResult(
            request.baseline,
            comparisons,
            diagnostics={"paired": True, "seed": context.seed},
        )


class ParetoFrontierAnalyzer(FrontierAnalyzer):
    @property
    def spec(self): return ComponentSpec("pareto_frontier", "1.0", "toolkit", "frontier_analyzer")
    def frontier(self, request, context):
        rows = request.options.get("rows", [])
        directions = request.options.get("directions", {})
        frontier = pareto_frontier(rows, request.metrics, directions)
        weights = request.options.get("weights")
        ranking = None
        if weights:
            ranking = sorted(
                (
                    {**row, "scalarized_score": scalarized_score(row, weights, directions)}
                    for row in rows
                ),
                key=lambda row: row["scalarized_score"],
                reverse=True,
            )
        return AnalysisResult(
            self.spec.name,
            {"frontier": frontier, "ranking": ranking},
            diagnostics={"directions": directions, "objective_count": len(request.metrics)},
        )
