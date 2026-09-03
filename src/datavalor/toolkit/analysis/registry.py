"""Typed extension registries for analysis."""

from datavalor.core import Registry

from .interfaces import Analyzer, FrontierAnalyzer, ResultComparator

ANALYZERS = Registry[Analyzer]("toolkit.analysis.analyzers")
RESULT_COMPARATORS = Registry[ResultComparator]("toolkit.analysis.comparators")
FRONTIER_ANALYZERS = Registry[FrontierAnalyzer]("toolkit.analysis.frontiers")

