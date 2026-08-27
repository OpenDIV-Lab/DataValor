"""Typed extension registries for DataProf."""

from datavalor.core import Registry

from .interfaces import DataProfiler, ProfileComparator, ProfileMetric

PROFILE_METRICS = Registry[ProfileMetric]("data_prof.metrics")
PROFILERS = Registry[DataProfiler]("data_prof.profilers")
PROFILE_COMPARATORS = Registry[ProfileComparator]("data_prof.comparators")

