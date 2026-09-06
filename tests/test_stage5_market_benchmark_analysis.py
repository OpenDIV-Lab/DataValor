from decimal import Decimal

import pytest

from datavalor.core import ActorProfile, ActorRole, DataProduct, DataReference, RunContext
from datavalor.data_market import (
    ContributionRevenueAllocator,
    DiscoveryQuery,
    InMemoryMarketCatalog,
    InMemoryParticipantRepository,
    Listing,
    ListingStatus,
    MarketSnapshot,
    ParticipantQuery,
)
from datavalor.data_market.simulation import (
    ContextualShadingStrategy,
    FiniteMarketSimulator,
    FixedReserveSellerStrategy,
    TruthfulStrategy,
)
from datavalor.data_price import FirstPriceAuction, Money, Payment
from datavalor.toolkit.analysis import (
    AnalysisRequest,
    BootstrapAnalyzer,
    ComparisonRequest,
    PairedComparator,
    ParetoFrontierAnalyzer,
    paired_bootstrap_difference,
    regret_summary,
    scalarized_score,
)
from datavalor.toolkit.benchmark import (
    BenchmarkCase,
    BenchmarkSpec,
    MarketOutcomeMetric,
    MatrixBenchmarkRunner,
)


def _product(pid="p1", tags=("mobility",)):
    return DataProduct(pid, "Mobility data", DataReference("memory://" + pid, "json"), "owner", tags=tags)


def test_catalog_publish_discover_rights_and_withdraw():
    catalog = InMemoryMarketCatalog()
    product = _product()
    listing = Listing("l1", product, "owner", ListingStatus.DRAFT)
    catalog.publish(listing, RunContext("r"))
    assert catalog.discover(DiscoveryQuery(text="mobility", tags=("mobility",)), RunContext("r"))[0].listing_id == "l1"
    catalog.withdraw("l1", RunContext("r2"))
    assert not catalog.discover(DiscoveryQuery(), RunContext("r"))
    assert len(catalog.history) == 2


def test_catalog_filters_rights_and_metadata():
    product = DataProduct("p", "Restricted", DataReference("memory://p", "json"), "o", metadata={"domain": "health"})
    listing = Listing("l", product, "o", ListingStatus.ACTIVE, terms={"tier": "premium"})
    catalog = InMemoryMarketCatalog(); catalog.publish(listing, RunContext("r"))
    assert not catalog.discover(DiscoveryQuery(rights_required=product.rights.__class__(commercial_use=True)), RunContext("r"))
    assert catalog.discover(DiscoveryQuery(filters={"domain": "health"}), RunContext("r"))[0].listing_id == "l"


def test_participant_repository_role_and_filter():
    repo = InMemoryParticipantRepository()
    repo.upsert(ActorProfile("b", ActorRole.BUYER, metadata={"region": "east"}), RunContext("r"))
    repo.upsert(ActorProfile("s", ActorRole.SUPPLIER, metadata={"region": "west"}), RunContext("r"))
    assert [p.actor_id for p in repo.search(ParticipantQuery(roles=("buyer",)), RunContext("r"))] == ["b"]
    assert repo.search(ParticipantQuery(filters={"region": "west"}), RunContext("r"))[0].actor_id == "s"


def test_contribution_revenue_allocator_reconciles_and_clamps_negative():
    allocator = ContributionRevenueAllocator()
    actors = (ActorProfile("a", ActorRole.SUPPLIER), ActorProfile("b", ActorRole.SUPPLIER))
    result = allocator.allocate(Money(Decimal("10.00")), actors, {"a": Decimal("2"), "b": Decimal("1")}, RunContext("r"))
    assert sum(share.amount.amount for share in result.shares) == Decimal("10.00")
    assert result.shares[0].amount.amount == Decimal("6.67")
    fallback = allocator.allocate(Money(Decimal("1")), actors, {"a": -1, "b": 0}, RunContext("r"))
    assert fallback.diagnostics["basis"] == "equal_fallback"


def _snapshot():
    product = _product()
    buyer = ActorProfile("buyer", ActorRole.BUYER, budget=Decimal("100"), preferences={"value": "20", "product_id": product.product_id})
    seller = ActorProfile("seller", ActorRole.SUPPLIER, preferences={"product_id": product.product_id})
    listing = Listing("l", product, "seller", ListingStatus.ACTIVE)
    return MarketSnapshot((listing,), (buyer, seller)), product


def test_simulator_assigns_distinct_actors_and_tracks_summary():
    snapshot, product = _snapshot()
    report = FiniteMarketSimulator(FirstPriceAuction()).run(snapshot, (TruthfulStrategy(), FixedReserveSellerStrategy(5)), 3, RunContext("sim", metadata={"products": (product,), "strategy_actors": ("buyer", "seller")}))
    assert report.summary["rounds"] == 3
    assert report.summary["sold_rounds"] == 3
    assert report.steps[0].diagnostics["actor_ids"] == ("buyer", "seller")
    assert report.diagnostics["equilibrium_claimed"] is False


def test_contextual_strategy_exposes_features():
    snapshot, _ = _snapshot()
    observation = __import__("datavalor.data_market.simulation", fromlist=["MarketObservation"]).MarketObservation(2, snapshot.participants[0], snapshot, metadata={"total_rounds": 4})
    decision = ContextualShadingStrategy().decide(observation, RunContext("r"))
    assert "features" in decision.state
    assert 0.2 <= decision.state["shading"] <= 1.0


def test_matrix_benchmark_has_stable_raw_observations_and_aggregates():
    def component(case, context):
        return {"outcome": case.parameters["factory"](context)}

    class Result:
        welfare = Decimal("10")
        seller_revenue = {"s": Money(Decimal("4"))}
        allocations = (1,)
        payments = (Payment("b", "s", Money(Decimal("4")), "test"),)

    case = BenchmarkCase("c", {}, parameters={"factory": lambda context: Result(), "optimal_welfare": 20})
    benchmark = BenchmarkSpec("b", ("m",), (case,), ("outcome",), repetitions=3, seed=4)
    report = MatrixBenchmarkRunner({"m": component}, {"outcome": MarketOutcomeMetric()}).run(benchmark, RunContext("r"))
    assert len(report.observations) == 3
    assert report.diagnostics["observation_count"] == 3
    assert report.aggregates["m"]["welfare"]["mean"] == 10
    assert len({obs.diagnostics["seed"] for obs in report.observations}) == 3


def test_matrix_benchmark_error_can_be_retained():
    case = BenchmarkCase("c", {}, parameters={})
    benchmark = BenchmarkSpec("b", ("m",), (case,), (), repetitions=1, parameters={"continue_on_error": True})
    report = MatrixBenchmarkRunner({"m": lambda case, context: 1 / 0}, {}).run(benchmark, RunContext("r"))
    assert report.diagnostics["failed_count"] == 1
    assert report.observations[0].diagnostics["error"] == "ZeroDivisionError"


def test_analysis_helpers_include_uncertainty_and_directions():
    interval = paired_bootstrap_difference([1, 2, 3], [2, 4, 5], samples=100, seed=2)
    assert interval["mean_difference"] == pytest.approx(5 / 3)
    assert regret_summary([1, 3, 2])["cumulative_regret"] == 3
    assert scalarized_score({"welfare": 10, "cost": 2}, {"welfare": 1, "cost": 1}, {"cost": "min"}) == 8
    rows = [{"name": "a", "welfare": 10, "cost": 5}, {"name": "b", "welfare": 9, "cost": 3}, {"name": "c", "welfare": 8, "cost": 6}]
    result = ParetoFrontierAnalyzer().frontier(AnalysisRequest((), ("welfare", "cost"), options={"rows": rows, "directions": {"cost": "min"}, "weights": {"welfare": 1, "cost": 0}}), RunContext("r"))
    assert {row["name"] for row in result.statistics["frontier"]} == {"a", "b"}


def test_analyzers_return_warnings_and_paired_comparisons():
    result = BootstrapAnalyzer().analyze(AnalysisRequest((), ("x",), options={"x": [1, 2], "samples": 20}), RunContext("r"))
    assert result.statistics["x"]["n"] == 2
    comparison = PairedComparator().compare(ComparisonRequest("base", ("candidate",), (), ("x",), {"base": [1, 2], "candidate": [2, 4]}), RunContext("r"))
    assert comparison.comparisons["candidate"]["mean_difference"] == 1.5
