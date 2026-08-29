"""Market benchmark metrics and matrix runner."""

from __future__ import annotations

import random

from datavalor.core import ComponentSpec

from .interfaces import BenchmarkMetric, BenchmarkRunner
from .models import BenchmarkObservation, BenchmarkReport


class MarketOutcomeMetric(BenchmarkMetric):
    @property
    def spec(self): return ComponentSpec("market.outcome", "1.0", "toolkit", "benchmark_metric")

    def measure(self, case, outputs, context):
        outcome = outputs.get("outcome")
        payload = getattr(outcome, "payload", outcome)
        if payload is None: return {"welfare": None, "seller_revenue": None, "allocation_count": 0}
        revenue = sum(float(m.amount) for m in getattr(payload, "seller_revenue", {}).values())
        return {"welfare": float(payload.welfare) if payload.welfare is not None else None, "seller_revenue": revenue, "allocation_count": len(payload.allocations), "payment_count": len(payload.payments)}


class MatrixBenchmarkRunner(BenchmarkRunner):
    def __init__(self, components=None, metrics=None): self.components, self.metrics = components or {}, metrics or {}

    @property
    def spec(self): return ComponentSpec("matrix_benchmark", "1.0", "toolkit", "benchmark_runner")

    def run(self, benchmark, context):
        observations = []; rng = random.Random(benchmark.seed)
        for component_name in benchmark.components:
            component = self.components[component_name]
            for case in benchmark.cases:
                for repetition in range(benchmark.repetitions):
                    local = type(context)(**{**context.__dict__, "seed": rng.randrange(2**32)})
                    output = component(case, local) if callable(component) else component
                    outputs = output if isinstance(output, dict) else {"result": output}
                    measurements = {}
                    for metric_name in benchmark.metrics:
                        metric = self.metrics[metric_name]; measurements.update(metric.measure(case, outputs, local))
                    observations.append(BenchmarkObservation(component_name, case.case_id, repetition, tuple(), measurements))
        return BenchmarkReport(benchmark.benchmark_id, tuple(observations), diagnostics={"raw_observations_first": True})


__all__ = ["MarketOutcomeMetric", "MatrixBenchmarkRunner"]
