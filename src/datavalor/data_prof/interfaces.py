"""Extension interfaces for DataProf."""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Mapping

from datavalor.core import BaseComponent, DataProduct, RunContext

from .models import DatasetProfile, ProfileComparison, ProfileRequest


class ProfileMetric(BaseComponent):
    """Compute one reusable descriptive property without judging quality."""

    @abstractmethod
    def measure(
        self,
        product: DataProduct,
        field: str | None,
        context: RunContext,
    ) -> Mapping[str, Any]:
        """Return named descriptive facts for a dataset or field."""


class DataProfiler(BaseComponent):
    """Build a dataset profile from registered or internal profile metrics."""

    @abstractmethod
    def profile(
        self,
        product: DataProduct,
        request: ProfileRequest,
        context: RunContext,
    ) -> DatasetProfile:
        """Create a reproducible descriptive profile."""


class ProfileComparator(BaseComponent):
    """Compare profile facts without assigning a quality or value score."""

    @abstractmethod
    def compare(
        self,
        reference: DatasetProfile,
        current: DatasetProfile,
        context: RunContext,
    ) -> ProfileComparison:
        """Return field- and dataset-level descriptive differences."""

