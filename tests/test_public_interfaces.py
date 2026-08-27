import importlib
import inspect

import pytest

from datavalor.core import BaseComponent
from datavalor.data_eval import DataEvaluator, QualityMetric, TaskUtilityEvaluator
from datavalor.data_gov import (
    DataCleaner,
    DataStandardizer,
    MetadataCatalog,
    MetadataExtractor,
    PolicyEvaluator,
    SecurityScanner,
)
from datavalor.data_market import (
    IncentivePolicy,
    MarketCatalog,
    MarketSimulator,
    ParticipantRepository,
    ParticipantStrategy,
    RevenueAllocator,
    TransactionProcessor,
)
from datavalor.data_price import OnlinePricingModel, PriceConstraint, PricingMechanism, PricingModel
from datavalor.data_prof import DataProfiler, ProfileComparator, ProfileMetric
from datavalor.data_query import (
    DataAgent,
    QueryAuthorizer,
    QueryExecutor,
    QueryPlanner,
    ResultGuard,
)
from datavalor.data_value import (
    ContributionValuator,
    DataValuator,
    TrainableValuator,
    UtilityFunction,
)
from datavalor.toolkit.analysis import Analyzer, FrontierAnalyzer, ResultComparator
from datavalor.toolkit.benchmark import (
    BenchmarkDataProvider,
    BenchmarkMetric,
    BenchmarkRunner,
    DataPerturbation,
)
from datavalor.toolkit.webui import ViewProvider, WebApplicationFactory

INTERFACES = (
    MetadataExtractor,
    MetadataCatalog,
    DataStandardizer,
    DataCleaner,
    SecurityScanner,
    PolicyEvaluator,
    ProfileMetric,
    DataProfiler,
    ProfileComparator,
    QualityMetric,
    DataEvaluator,
    TaskUtilityEvaluator,
    UtilityFunction,
    DataValuator,
    TrainableValuator,
    ContributionValuator,
    PricingModel,
    OnlinePricingModel,
    PriceConstraint,
    PricingMechanism,
    MarketCatalog,
    ParticipantRepository,
    IncentivePolicy,
    RevenueAllocator,
    TransactionProcessor,
    ParticipantStrategy,
    MarketSimulator,
    QueryAuthorizer,
    QueryPlanner,
    QueryExecutor,
    ResultGuard,
    DataAgent,
    BenchmarkDataProvider,
    DataPerturbation,
    BenchmarkMetric,
    BenchmarkRunner,
    Analyzer,
    ResultComparator,
    FrontierAnalyzer,
    ViewProvider,
    WebApplicationFactory,
)


@pytest.mark.parametrize("interface", INTERFACES)
def test_public_interfaces_are_abstract_components(interface):
    assert issubclass(interface, BaseComponent)
    assert inspect.isabstract(interface)
    with pytest.raises(TypeError):
        interface()


@pytest.mark.parametrize(
    "module",
    (
        "datavalor.core",
        "datavalor.data_gov",
        "datavalor.data_prof",
        "datavalor.data_eval",
        "datavalor.data_value",
        "datavalor.data_market",
        "datavalor.data_market.simulation",
        "datavalor.data_price",
        "datavalor.data_query",
        "datavalor.toolkit",
        "datavalor.toolkit.benchmark",
        "datavalor.toolkit.analysis",
        "datavalor.toolkit.webui",
    ),
)
def test_public_packages_import_without_optional_dependencies(module):
    assert importlib.import_module(module) is not None
