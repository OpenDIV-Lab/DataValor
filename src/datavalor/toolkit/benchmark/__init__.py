"""Cross-module benchmark protocols and runners."""

from .data_perturbations import apply_perturbations, split_records
from .data_sources import (
    BaseDistribution,
    DistributionBatch,
    HuggingFaceProvider,
    LocalDatasetProvider,
    ParametricProvider,
    SklearnDatasetProvider,
    SklearnGeneratorProvider,
)
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
    "BaseDistribution",
    "DistributionBatch",
    "HuggingFaceProvider",
    "LocalDatasetProvider",
    "ParametricProvider",
    "SklearnDatasetProvider",
    "SklearnGeneratorProvider",
    "apply_perturbations",
    "split_records",
]
