"""In-memory market operations and auditable revenue allocation baselines."""

from __future__ import annotations

from dataclasses import replace
from decimal import ROUND_DOWN, Decimal

from datavalor.core import ActorProfile, ComponentSpec
from datavalor.data_price import Money

from .interfaces import MarketCatalog, ParticipantRepository, RevenueAllocator
from .models import (
    DiscoveryQuery,
    Listing,
    ListingStatus,
    ParticipantQuery,
    RevenueAllocation,
    RevenueShare,
)


def _rights_satisfy(listing: Listing, query: DiscoveryQuery) -> bool:
    required = query.rights_required
    if required is None:
        return True
    available = listing.rights or listing.product.rights
    if not set(required.purposes).issubset(available.purposes):
        return False
    if required.commercial_use is True and available.commercial_use is not True:
        return False
    if required.redistribution is True and available.redistribution is not True:
        return False
    if required.jurisdictions and not set(required.jurisdictions).issubset(
        available.jurisdictions
    ):
        return False
    return True


class InMemoryMarketCatalog(MarketCatalog):
    """Auditable local listing catalog with practical discovery filters."""

    def __init__(self) -> None:
        self._listings: dict[str, Listing] = {}
        self._history: list[tuple[str, str, str]] = []

    @property
    def spec(self):
        return ComponentSpec(
            "market_catalog.memory",
            "1.0.0",
            "data_market",
            "market_catalog",
            capabilities=("publish", "withdraw", "search", "rights_filter"),
        )

    def publish(self, listing: Listing, context) -> Listing:
        if not listing.listing_id.strip():
            raise ValueError("listing_id must not be empty")
        if listing.status == ListingStatus.CLOSED:
            raise ValueError("closed listing cannot be published")
        published = replace(listing, status=ListingStatus.ACTIVE)
        self._listings[published.listing_id] = published
        self._history.append((context.run_id, "publish", published.listing_id))
        return published

    def withdraw(self, listing_id: str, context) -> Listing:
        if listing_id not in self._listings:
            raise KeyError(listing_id)
        withdrawn = replace(self._listings[listing_id], status=ListingStatus.CLOSED)
        self._listings[listing_id] = withdrawn
        self._history.append((context.run_id, "withdraw", listing_id))
        return withdrawn

    def discover(self, query: DiscoveryQuery, context) -> tuple[Listing, ...]:
        del context
        text = (query.text or "").casefold().strip()
        matches = []
        for listing in self._listings.values():
            if listing.status != ListingStatus.ACTIVE:
                continue
            product = listing.product
            haystack = " ".join(
                (product.title, product.description, " ".join(product.tags))
            ).casefold()
            if text and text not in haystack:
                continue
            if query.tags and not set(query.tags).issubset(product.tags):
                continue
            if not _rights_satisfy(listing, query):
                continue
            attributes = {
                **product.metadata,
                **listing.metadata,
                **listing.terms,
                "seller_id": listing.seller_id,
                "owner_id": product.owner_id,
            }
            if any(attributes.get(key) != value for key, value in query.filters.items()):
                continue
            matches.append(listing)
        matches.sort(key=lambda item: (item.product.title.casefold(), item.listing_id))
        return tuple(matches[: max(0, query.limit)])

    @property
    def history(self) -> tuple[tuple[str, str, str], ...]:
        return tuple(self._history)


class InMemoryParticipantRepository(ParticipantRepository):
    """Deterministic participant store used by local markets and tests."""

    def __init__(self) -> None:
        self._profiles: dict[str, ActorProfile] = {}

    @property
    def spec(self):
        return ComponentSpec(
            "participant_repository.memory",
            "1.0.0",
            "data_market",
            "participant_repository",
            capabilities=("upsert", "get", "role_filter"),
        )

    def upsert(self, profile: ActorProfile, context) -> ActorProfile:
        del context
        if not profile.actor_id.strip():
            raise ValueError("actor_id must not be empty")
        self._profiles[profile.actor_id] = profile
        return profile

    def get(self, actor_id: str, context) -> ActorProfile | None:
        del context
        return self._profiles.get(actor_id)

    def search(self, query: ParticipantQuery, context) -> tuple[ActorProfile, ...]:
        del context
        roles = set(query.roles)
        result = []
        for profile in self._profiles.values():
            if roles and profile.role.value not in roles:
                continue
            attributes = {**profile.metadata, **profile.preferences, **profile.constraints}
            if any(attributes.get(key) != value for key, value in query.filters.items()):
                continue
            result.append(profile)
        result.sort(key=lambda item: item.actor_id)
        return tuple(result[: max(0, query.limit)])


class ContributionRevenueAllocator(RevenueAllocator):
    """Allocate revenue by positive contribution and reconcile to the cent.

    Negative contributions are clamped to zero. If every weight is zero, an
    equal split is used. The residual created by currency quantization is
    assigned deterministically by descending fractional remainder.
    """

    def __init__(self, quantum="0.01") -> None:
        self.quantum = Decimal(str(quantum))
        if self.quantum <= 0:
            raise ValueError("revenue allocation quantum must be positive")

    @property
    def spec(self):
        return ComponentSpec(
            "revenue.contribution",
            "1.0.0",
            "data_market",
            "revenue_allocator",
            capabilities=("contribution", "exact_reconciliation", "decimal"),
        )

    def allocate(self, total, participants, contributions, context):
        del context
        if total.amount < 0:
            raise ValueError("revenue total must be non-negative")
        if not participants:
            if total.amount != 0:
                raise ValueError("cannot allocate non-zero revenue without participants")
            return RevenueAllocation(total, (), self.spec.name)
        actor_ids = [profile.actor_id for profile in participants]
        if len(set(actor_ids)) != len(actor_ids):
            raise ValueError("revenue participants must be unique")
        weights = {
            actor_id: max(Decimal("0"), Decimal(str(contributions.get(actor_id, 0))))
            for actor_id in actor_ids
        }
        basis = "positive_contribution"
        weight_sum = sum(weights.values(), Decimal("0"))
        if weight_sum == 0:
            weights = {actor_id: Decimal("1") for actor_id in actor_ids}
            weight_sum = Decimal(len(actor_ids))
            basis = "equal_fallback"
        raw = {actor_id: total.amount * weights[actor_id] / weight_sum for actor_id in actor_ids}
        amounts = {
            actor_id: value.quantize(self.quantum, rounding=ROUND_DOWN)
            for actor_id, value in raw.items()
        }
        residual = total.amount - sum(amounts.values(), Decimal("0"))
        order = sorted(actor_ids, key=lambda actor_id: (raw[actor_id] - amounts[actor_id], actor_id), reverse=True)
        while residual >= self.quantum:
            for actor_id in order:
                if residual < self.quantum:
                    break
                amounts[actor_id] += self.quantum
                residual -= self.quantum
        if residual:
            amounts[order[0]] += residual
            residual = Decimal("0")
        shares = tuple(
            RevenueShare(
                actor_id,
                Money(amounts[actor_id], total.currency),
                basis,
                float(weights[actor_id] / weight_sum),
                {"raw_amount": str(raw[actor_id])},
            )
            for actor_id in actor_ids
        )
        return RevenueAllocation(
            total,
            shares,
            self.spec.name,
            {
                "basis": basis,
                "quantum": str(self.quantum),
                "reconciled": sum((share.amount.amount for share in shares), Decimal("0"))
                == total.amount,
                "negative_contributions_clamped": tuple(
                    actor_id
                    for actor_id in actor_ids
                    if Decimal(str(contributions.get(actor_id, 0))) < 0
                ),
            },
        )


__all__ = [
    "ContributionRevenueAllocator",
    "InMemoryMarketCatalog",
    "InMemoryParticipantRepository",
]
