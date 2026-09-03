"""Ocean.py asset-market connector mapped to DataValor listings/transactions."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from datavalor.core import ComponentSpec, RunContext, require_capability
from datavalor.data_market.interfaces import MarketCatalog, TransactionProcessor
from datavalor.data_market.models import DiscoveryQuery, Listing, ListingStatus, TransactionRecord

from ._utils import call_remote, normalize_mapping


class OceanMarketCatalog(MarketCatalog):
    """Register/discover assets through an injected Ocean client or SDK.

    Blockchain transactions are never initiated implicitly: callers provide a
    client exposing the desired method and explicitly configure ``publish``.
    """

    def __init__(self, *, client: Any = None, ocean_factory: Callable[..., Any] | None = None,
                 endpoint: str | None = None, retries: int = 1, timeout: float = 30.0) -> None:
        self.client, self.ocean_factory, self.endpoint = client, ocean_factory, endpoint
        self.retries, self.timeout = retries, timeout
        self._listings: dict[str, Listing] = {}

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("ocean.catalog", "0.1.0", "data_market", "market_catalog",
                             capabilities=("asset_registration", "discovery", "consumption"), requires=("ocean-lib>=0.1",))

    def _client(self) -> Any:
        if self.client is not None:
            return self.client
        if self.ocean_factory is not None:
            self.client = self.ocean_factory(self.endpoint)
            return self.client
        ocean = require_capability("ocean_py", "ocean_lib", distribution="ocean-lib", extra="market")
        cls = getattr(ocean, "Ocean", None)
        if cls is None:
            raise RuntimeError("ocean_lib has no Ocean client; inject ocean_factory")
        self.client = cls()
        return self.client

    @staticmethod
    def _asset(listing: Listing) -> dict[str, Any]:
        return {"id": listing.listing_id, "product_id": listing.product.product_id,
                "name": listing.product.title, "seller_id": listing.seller_id,
                "description": listing.product.description, "rights": listing.rights or listing.product.rights,
                "terms": dict(listing.terms), "metadata": dict(listing.metadata)}

    def publish(self, listing: Listing, context: RunContext) -> Listing:
        client = self._client()
        method = getattr(client, "publish", None) or getattr(client, "register_asset", None) or getattr(client, "create_asset", None)
        if not callable(method):
            raise RuntimeError("Ocean client exposes no publish/register_asset/create_asset method")
        call_remote(method, self._asset(listing), retries=self.retries, timeout=self.timeout)
        active = Listing(listing.listing_id, listing.product, listing.seller_id, ListingStatus.ACTIVE,
                       listing.rights, listing.terms, listing.created_at,
                       {**listing.metadata, "connector": "ocean", "run_id": context.run_id})
        self._listings[active.listing_id] = active
        return active

    def withdraw(self, listing_id: str, context: RunContext) -> Listing:
        client = self._client()
        method = getattr(client, "withdraw", None) or getattr(client, "unpublish", None)
        if not callable(method):
            raise RuntimeError("Ocean client exposes no withdraw/unpublish method")
        call_remote(method, listing_id, retries=self.retries, timeout=self.timeout)
        listing = self._listings.get(listing_id)
        if listing is None:
            raise KeyError(f"listing {listing_id!r} is not known to this connector")
        closed = Listing(listing.listing_id, listing.product, listing.seller_id, ListingStatus.CLOSED,
                         listing.rights, listing.terms, listing.created_at,
                         {**listing.metadata, "withdrawn": True, "run_id": context.run_id})
        self._listings[listing_id] = closed
        return closed

    def discover(self, query: DiscoveryQuery, context: RunContext) -> tuple[Listing, ...]:
        client = self._client()
        method = getattr(client, "discover", None) or getattr(client, "search_assets", None) or getattr(client, "search", None)
        if not callable(method):
            raise RuntimeError("Ocean client exposes no discover/search_assets/search method")
        values = call_remote(method, query.text or "", limit=query.limit, retries=self.retries, timeout=self.timeout)
        listings = []
        for item in values or ():
            if isinstance(item, Listing):
                listings.append(item)
            elif isinstance(item, Mapping):
                listing_id = str(item.get("listing_id", item.get("id", "")))
                if listing_id in self._listings:
                    listings.append(self._listings[listing_id])
        return tuple(listings[: query.limit])


class OceanTransactionProcessor(TransactionProcessor):
    def __init__(self, *, client: Any = None, consumer: Callable[..., Any] | None = None,
                 retries: int = 1, timeout: float = 60.0) -> None:
        self.client, self.consumer, self.retries, self.timeout = client, consumer, retries, timeout

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("ocean.transaction", "0.1.0", "data_market", "transaction_processor",
                             capabilities=("consumption",), requires=("ocean-lib>=0.1",))

    def execute(self, outcome, context: RunContext) -> TransactionRecord:
        consumer = self.consumer
        if consumer is None:
            ocean = require_capability("ocean_py", "ocean_lib", distribution="ocean-lib", extra="market")
            consumer = getattr(self.client or ocean, "consume", None)
        if not callable(consumer):
            raise RuntimeError("Ocean transaction requires an injected consumer/client.consume")
        result = call_remote(consumer, outcome=outcome, context=context, retries=self.retries, timeout=self.timeout)
        return TransactionRecord(f"ocean:{context.run_id}", outcome, "succeeded",
                                 diagnostics={"backend": "ocean", "run_id": context.run_id, "external_result": normalize_mapping(result)})


__all__ = ["OceanMarketCatalog", "OceanTransactionProcessor"]
