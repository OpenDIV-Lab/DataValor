"""Cross-module benchmark protocols and runners."""

from .interfaces import BenchmarkDataProvider, BenchmarkMetric, BenchmarkRunner, DataPerturbation
from .models import BenchmarkCase, BenchmarkObservation, BenchmarkReport, BenchmarkSpec
from .registry import (
    BENCHMARK_DATA_PROVIDERS,
    BENCHMARK_METRICS,
    BENCHMARK_RUNNERS,
    DATA_PERTURBATIONS,
)

__all__ = [
    "BENCHMARK_DATA_PROVIDERS",
    "BENCHMARK_METRICS",
    "BENCHMARK_RUNNERS",
    "DATA_PERTURBATIONS",
    "BenchmarkCase",
    "BenchmarkDataProvider",
    "BenchmarkMetric",
    "BenchmarkObservation",
    "BenchmarkReport",
    "BenchmarkRunner",
    "BenchmarkSpec",
    "DataPerturbation",
]
