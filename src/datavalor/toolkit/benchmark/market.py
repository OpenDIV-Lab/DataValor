"""Market benchmark metrics, stable experiment matrices, and aggregation."""

from __future__ import annotations

import hashlib
import math
import statistics
from collections import defaultdict

from datavalor.core import ComponentSpec

from .interfaces import BenchmarkMetric, BenchmarkRunner
from .models import BenchmarkObservation, BenchmarkReport


def _payload(value):
    return getattr(value, "payload", value)


def _stable_seed(base: int, component: str, case_id: str, repetition: int) -> int:
    text = f"{base}:{component}:{case_id}:{repetition}".encode()
    return int.from_bytes(hashlib.sha256(text).digest()[:4], "big")


class MarketOutcomeMetric(BenchmarkMetric):
    """Measure allocation, payment, revenue, welfare, and optional efficiency."""

    @property
    def spec(self):
        return ComponentSpec("market.outcome", "1.1", "toolkit", "benchmark_metric")

    def measure(self, case, outputs, context):
        del context
        outcome = _payload(outputs.get("outcome") or outputs.get("result"))
        if outcome is None:
            return {
                "welfare": None,
                "seller_revenue": None,
                "allocation_count": 0,
                "payment_count": 0,
                "trade": False,
                "efficiency": None,
            }
        revenue = sum(float(item.amount) for item in outcome.seller_revenue.values())
        welfare = float(outcome.welfare) if outcome.welfare is not None else None
        optimal = case.parameters.get("optimal_welfare")
        efficiency = None
        if optimal is not None and float(optimal) > 0 and welfare is not None:
            efficiency = welfare / float(optimal)
        payment_total = sum(float(item.amount.amount) for item in outcome.payments)
        return {
            "welfare": welfare,
            "seller_revenue": revenue,
            "payment_total": payment_total,
            "allocation_count": len(outcome.allocations),
            "payment_count": len(outcome.payments),
            "trade": bool(outcome.allocations),
            "efficiency": efficiency,
        }


class SimulationReportMetric(BenchmarkMetric):
    """Measure repeated-market conversion, revenue, welfare, and volatility."""

    @property
    def spec(self):
        return ComponentSpec("market.simulation", "1.0", "toolkit", "benchmark_metric")

    def measure(self, case, outputs, context):
        del case, context
        report = _payload(outputs.get("report") or outputs.get("result"))
        if report is None:
            return {
                "conversion_rate": 0.0,
                "total_revenue": 0.0,
                "mean_revenue": 0.0,
                "revenue_std": 0.0,
                "mean_welfare": None,
            }
        revenues = []
        welfares = []
        for step in report.steps:
            if step.outcome is None:
                revenues.append(0.0)
                continue
            revenues.append(sum(float(item.amount.amount) for item in step.outcome.payments))
            if step.outcome.welfare is not None:
                welfares.append(float(step.outcome.welfare))
        sold = sum(
            1 for step in report.steps if step.outcome is not None and step.outcome.allocations
        )
        return {
            "conversion_rate": sold / len(report.steps) if report.steps else 0.0,
            "total_revenue": sum(revenues),
            "mean_revenue": statistics.fmean(revenues) if revenues else 0.0,
            "revenue_std": statistics.pstdev(revenues) if len(revenues) > 1 else 0.0,
            "mean_welfare": statistics.fmean(welfares) if welfares else None,
            "rounds": len(report.steps),
        }


def aggregate_observations(observations):
    """Aggregate numeric raw observations by component without discarding them."""

    grouped = defaultdict(lambda: defaultdict(list))
    failures = defaultdict(int)
    for observation in observations:
        if observation.diagnostics.get("error"):
            failures[observation.component] += 1
        for name, value in observation.measurements.items():
            if isinstance(value, bool):
                grouped[observation.component][name].append(float(value))
            elif isinstance(value, (int, float)) and value is not None and math.isfinite(value):
                grouped[observation.component][name].append(float(value))
    result = {}
    for component, metrics in grouped.items():
        result[component] = {}
        for name, values in metrics.items():
            result[component][name] = {
                "n": len(values),
                "mean": statistics.fmean(values),
                "std": statistics.stdev(values) if len(values) > 1 else 0.0,
                "min": min(values),
                "max": max(values),
            }
        result[component]["failures"] = failures[component]
    for component, count in failures.items():
        result.setdefault(component, {})["failures"] = count
    return result


class MatrixBenchmarkRunner(BenchmarkRunner):
    """Run component × case × repetition with stable per-cell seeds."""

    def __init__(self, components=None, metrics=None):
        self.components = components or {}
        self.metrics = metrics or {}

    @property
    def spec(self):
        return ComponentSpec("matrix_benchmark", "1.1", "toolkit", "benchmark_runner")

    def run(self, benchmark, context):
        if benchmark.repetitions <= 0:
            raise ValueError("benchmark repetitions must be positive")
        missing_components = set(benchmark.components) - self.components.keys()
        missing_metrics = set(benchmark.metrics) - self.metrics.keys()
        if missing_components:
            raise KeyError(f"unknown benchmark components: {sorted(missing_components)}")
        if missing_metrics:
            raise KeyError(f"unknown benchmark metrics: {sorted(missing_metrics)}")
        continue_on_error = bool(benchmark.parameters.get("continue_on_error", False))
        observations = []
        for component_name in benchmark.components:
            component = self.components[component_name]
            for case in benchmark.cases:
                for repetition in range(benchmark.repetitions):
                    seed = _stable_seed(benchmark.seed, component_name, case.case_id, repetition)
                    local = type(context)(**{**context.__dict__, "seed": seed})
                    try:
                        output = component(case, local) if callable(component) else component
                        outputs = output if isinstance(output, dict) else {"result": output}
                        measurements = {}
                        for metric_name in benchmark.metrics:
                            measurements.update(
                                self.metrics[metric_name].measure(case, outputs, local)
                            )
                        diagnostics = {"seed": seed, "status": "succeeded"}
                    except Exception as exc:
                        if not continue_on_error:
                            raise
                        measurements = {}
                        diagnostics = {
                            "seed": seed,
                            "status": "failed",
                            "error": type(exc).__name__,
                            "message": str(exc),
                        }
                    observations.append(
                        BenchmarkObservation(
                            component_name,
                            case.case_id,
                            repetition,
                            tuple(),
                            measurements,
                            diagnostics,
                        )
                    )
        aggregates = aggregate_observations(observations)
        return BenchmarkReport(
            benchmark.benchmark_id,
            tuple(observations),
            aggregates,
            diagnostics={
                "raw_observations_first": True,
                "seed_method": "sha256(component,case,repetition)",
                "observation_count": len(observations),
                "failed_count": sum(
                    1 for item in observations if item.diagnostics.get("status") == "failed"
                ),
            },
        )


__all__ = [
    "MarketOutcomeMetric",
    "MatrixBenchmarkRunner",
    "SimulationReportMetric",
    "aggregate_observations",
]
