"""Extension interfaces for DataValue."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Sequence

from datavalor.core import BaseComponent, DataProduct, RunContext, TaskContext

from .models import (
    ContributionReport,
    ContributionRequest,
    TrainingReport,
    ValuationReport,
    ValuationRequest,
)


class UtilityFunction(BaseComponent):
    """Score the downstream utility of a selected subset for one task."""

    @abstractmethod
    def score(
        self,
        product: DataProduct,
        selection: tuple[str, ...],
        task: TaskContext,
        context: RunContext,
    ) -> float:
        """Return task utility under an explicitly identified selection."""


class DataValuator(BaseComponent):
    """Estimate value while keeping it distinct from bids and prices."""

    @abstractmethod
    def value(self, request: ValuationRequest, context: RunContext) -> ValuationReport:
        """Estimate values for all targets in a request."""


class TrainableValuator(DataValuator):
    """Valuator that learns from historical valuation requests and outcomes."""

    @abstractmethod
    def fit(
        self,
        requests: Sequence[ValuationRequest],
        observed_values: Sequence[float],
        context: RunContext,
    ) -> TrainingReport:
        """Fit internal state and return auditable training metadata."""


class ContributionValuator(BaseComponent):
    """Estimate marginal or coalitional contributions of data units."""

    @abstractmethod
    def value_contributions(
        self,
        request: ContributionRequest,
        utility: UtilityFunction,
        context: RunContext,
    ) -> ContributionReport:
        """Return per-unit contributions with computation diagnostics."""

