"""DataProf: statistical profiling and dataset characterization."""

from .advanced import (
    CategoricalConcentrationMetric,
    DriftAnalyzer,
    DriftFieldResult,
    DriftReport,
    PairwiseCorrelationMetric,
    RobustStatisticsMetric,
    stratified_sample,
)
from .builtins import BasicDataProfiler, BasicProfileComparator, BasicProfileMetric
from .interfaces import DataProfiler, ProfileComparator, ProfileMetric
from .models import (
    DatasetProfile,
    FieldProfile,
    ProfileComparison,
    ProfileDifference,
    ProfileRequest,
)
from .registry import PROFILE_COMPARATORS, PROFILE_METRICS, PROFILERS

for _component, _registry in (
    (BasicDataProfiler, PROFILERS),
    (BasicProfileComparator, PROFILE_COMPARATORS),
    (BasicProfileMetric, PROFILE_METRICS),
    (RobustStatisticsMetric, PROFILE_METRICS),
    (CategoricalConcentrationMetric, PROFILE_METRICS),
    (PairwiseCorrelationMetric, PROFILE_METRICS),
):
    if _component().spec.name not in _registry:
        _registry.register(_component().spec, _component)

__all__ = [
    "PROFILE_COMPARATORS",
    "PROFILE_METRICS",
    "PROFILERS",
    "DataProfiler",
    "DatasetProfile",
    "FieldProfile",
    "ProfileComparator",
    "ProfileComparison",
    "ProfileDifference",
    "ProfileMetric",
    "ProfileRequest",
    "BasicDataProfiler",
    "BasicProfileComparator",
    "BasicProfileMetric",
    "RobustStatisticsMetric",
    "CategoricalConcentrationMetric",
    "PairwiseCorrelationMetric",
    "DriftAnalyzer",
    "DriftFieldResult",
    "DriftReport",
    "stratified_sample",
]
