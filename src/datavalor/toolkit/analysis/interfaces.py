"""Extension interfaces for generic analysis and component comparison."""

from __future__ import annotations

from abc import abstractmethod

from datavalor.core import BaseComponent, RunContext

from .models import AnalysisRequest, AnalysisResult, ComparisonRequest, ComparisonResult


class Analyzer(BaseComponent):
    """Analyze versioned artifacts without assuming one business module."""

    @abstractmethod
    def analyze(self, request: AnalysisRequest, context: RunContext) -> AnalysisResult:
        """Return statistics, warnings, and derived artifacts."""


class ResultComparator(BaseComponent):
    """Compare methods while preserving uncertainty and design assumptions."""

    @abstractmethod
    def compare(self, request: ComparisonRequest, context: RunContext) -> ComparisonResult:
        """Return effect estimates and comparison diagnostics."""


class FrontierAnalyzer(BaseComponent):
    """Compute constrained Pareto frontiers over named objectives."""

    @abstractmethod
    def frontier(self, request: AnalysisRequest, context: RunContext) -> AnalysisResult:
        """Return non-dominated candidates and objective directions."""

