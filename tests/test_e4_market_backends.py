"""Offline E4 tests using injected Mesa/PySyft/Ocean stand-ins."""


from datavalor.core import ActorProfile, ActorRole, DataProduct, DataReference, RunContext
from datavalor.data_gov.backends.syft import SyftOwnerExecution, SyftPolicyEvaluator
from datavalor.data_market import Listing, ListingStatus, MarketSnapshot
from datavalor.data_market.backends.ocean import OceanMarketCatalog, OceanTransactionProcessor
from datavalor.data_market.backends.syft import SyftTransactionProcessor
from datavalor.data_market.simulation import MesaMarketSimulator, TruthfulStrategy
from datavalor.data_price import PricingOutcome


def product():
    return DataProduct("p1", "demo", DataReference("memory://p1", "records"), "seller")


def listing():
    return Listing("l1", product(), "seller", ListingStatus.DRAFT)


def outcome():
    return PricingOutcome("test", (), ())


def test_mesa_adapter_uses_model_factory_and_datavalor_snapshot():
    class Model:
        def __init__(self):
            self.steps = 0

        def step(self):
            self.steps += 1

    seller = ActorProfile("buyer", ActorRole.BUYER, preferences={"value": 1, "product_id": "p1"})
    market = MarketSnapshot((listing(),), (seller,))
    model = Model()
    simulator = MesaMarketSimulator(model_factory=lambda **kwargs: model)
    report = simulator.run(market, (TruthfulStrategy(),), 2, RunContext("e4", metadata={"products": (product(),)}))
    assert len(report.steps) == 2
    assert model.steps == 2
    assert report.steps[0].diagnostics["backend"] == "mesa"


def test_syft_policy_and_owner_execution_are_rights_aware():
    governed = DataProduct("p1", "demo", DataReference("memory://p1", "records"), "seller",
                           rights=product().rights.__class__(purposes=("train",)))
    allowed = SyftPolicyEvaluator(checker=lambda **kwargs: {"allowed": True}).evaluate(
        governed, "train", None, RunContext("e4")
    )
    denied = SyftPolicyEvaluator().evaluate(governed, "publish", None, RunContext("e4"))
    assert allowed.decision.value == "allow"
    assert denied.decision.value == "deny"
    executed = SyftOwnerExecution(executor=lambda **kwargs: {"rows": 2}).execute(governed, "train", RunContext("e4"))
    assert executed["rows"] == 2


def test_ocean_catalog_and_transaction_keep_datavalor_models():
    class Client:
        def __init__(self):
            self.assets = []
            self.withdrawn = []

        def publish(self, asset):
            self.assets.append(asset)

        def withdraw(self, listing_id):
            self.withdrawn.append(listing_id)

        def discover(self, text, limit=100):
            return [{"id": "l1"}]

    client = Client()
    catalog = OceanMarketCatalog(client=client)
    active = catalog.publish(listing(), RunContext("e4"))
    assert active.status is ListingStatus.ACTIVE
    assert catalog.discover(type("Q", (), {"text": "demo", "limit": 10})(), RunContext("e4"))[0].listing_id == "l1"
    assert catalog.withdraw("l1", RunContext("e4")).status is ListingStatus.CLOSED
    tx = OceanTransactionProcessor(consumer=lambda **kwargs: {"tx": "0x1"}).execute(outcome(), RunContext("e4"))
    assert tx.status == "succeeded"
    syft = SyftTransactionProcessor(executor=lambda **kwargs: {"status": "partial"}).execute(outcome(), RunContext("e4"))
    assert syft.status == "partial"
