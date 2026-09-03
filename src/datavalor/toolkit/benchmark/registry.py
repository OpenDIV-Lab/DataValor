"""Typed extension registries for benchmarking."""

from datavalor.core import Registry

from .interfaces import BenchmarkDataProvider, BenchmarkMetric, BenchmarkRunner, DataPerturbation

BENCHMARK_DATA_PROVIDERS = Registry[BenchmarkDataProvider]("toolkit.benchmark.data")
DATA_PERTURBATIONS = Registry[DataPerturbation]("toolkit.benchmark.perturbations")
BENCHMARK_METRICS = Registry[BenchmarkMetric]("toolkit.benchmark.metrics")
BENCHMARK_RUNNERS = Registry[BenchmarkRunner]("toolkit.benchmark.runners")

