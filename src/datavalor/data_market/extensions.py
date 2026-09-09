"""Market-side lifecycle, incentive, reputation and settlement helpers.

DataPrice determines prices and allocations.  This module deals with what
happens around those results: which listing is visible, who receives an
incentive, whether a seller is reliable, and whether a transaction can be
recorded idempotently.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, Mapping, Sequence

from datavalor.core import ComponentSpec, RunContext, canonical_sha256
from datavalor.data_price import Money, PricingOutcome

from .interfaces import IncentivePolicy, TransactionProcessor
from .models import (
    Incentive,
    Listing,
    ListingStatus,
    MarketSnapshot,
    TransactionRecord,
)


def _canonical(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Money):
        return {"amount": str(value.amount), "currency": value.currency}
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    return value


def rank_listings(listings: Sequence[Listing], query_text: str | None = None, tags: Sequence[str] = (), preferences: Mapping[str, Any] | None = None) -> tuple[Listing, ...]:
    """Rank active listings by textual/tag fit and declared quality metadata."""
    text = (query_text or "").casefold().strip(); wanted = set(tags); preferences = preferences or {}

    def score(listing: Listing) -> tuple[float, str]:
        haystack = " ".join((listing.product.title, listing.product.description, " ".join(listing.product.tags))).casefold()
        text_score = 1.0 if text and text in haystack else 0.0
        tag_score = len(wanted.intersection(listing.product.tags)) / len(wanted) if wanted else 0.0
        quality = float(listing.metadata.get("quality", listing.product.metadata.get("quality", 0.0)) or 0.0)
        freshness = float(listing.metadata.get("freshness", listing.product.metadata.get("freshness", 0.0)) or 0.0)
        preferred_seller = 1.0 if preferences.get("seller_id") == listing.seller_id else 0.0
        return (2.0 * text_score + 1.5 * tag_score + 0.5 * max(0.0, min(1.0, quality)) + 0.25 * max(0.0, min(1.0, freshness)) + preferred_seller, listing.listing_id)

    return tuple(sorted((listing for listing in listings if listing.status is ListingStatus.ACTIVE), key=lambda item: score(item), reverse=True))


@dataclass(frozen=True)
class ReputationScore:
    actor_id: str
    completed: int
    failed: int
    disputed: int
    success_rate: Decimal
    reliability_score: Decimal
    evidence: Mapping[str, Any]


def score_reputation(actor_id: str, transactions: Sequence[TransactionRecord], dispute_ids: Sequence[str] = ()) -> ReputationScore:
    """Compute a transparent seller/participant reliability score."""
    disputes = set(dispute_ids); relevant = [record for record in transactions if actor_id in {share.actor_id for share in record.settlements} or record.diagnostics.get("seller_id") == actor_id]
    completed = sum(record.status in {"succeeded", "completed"} for record in relevant); failed = sum(record.status in {"failed", "partial", "denied"} for record in relevant); disputed = sum(record.transaction_id in disputes for record in relevant); total = len(relevant)
    success_rate = Decimal(completed) / Decimal(total) if total else Decimal("0")
    dispute_rate = Decimal(disputed) / Decimal(total) if total else Decimal("0")
    reliability = max(Decimal("0"), min(Decimal("1"), success_rate - Decimal("0.5") * dispute_rate))
    return ReputationScore(actor_id, completed, failed, disputed, success_rate, reliability, {"transaction_count": total, "dispute_ids": tuple(sorted(disputes.intersection({record.transaction_id for record in relevant})))})


class ContributionIncentivePolicy(IncentivePolicy):
    """Distribute a fixed incentive budget using positive contributions."""

    def __init__(self, budget: Any = 0, currency: str = "CNY", kind: str = "contribution_bonus"):
        self.budget, self.currency, self.kind = Decimal(str(budget)), currency, kind
        if self.budget < 0:
            raise ValueError("incentive budget must be non-negative")

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("incentive.contribution_budget", "1.0.0", "data_market", "incentive_policy", capabilities=("contribution", "budget", "decimal"))

    def compute(self, market: MarketSnapshot, outcome: PricingOutcome, context: RunContext) -> tuple[Incentive, ...]:
        contributions = context.config.get("contributions", {})
        actors = sorted({profile.actor_id for profile in market.participants} | {str(actor) for actor in contributions})
        weights = {actor: max(Decimal("0"), Decimal(str(contributions.get(actor, 0)))) for actor in actors}; denominator = sum(weights.values(), Decimal("0"))
        if denominator == 0 and actors:
            weights = {actor: Decimal("1") for actor in actors}; denominator = Decimal(len(actors))
        incentives = []
        for actor in actors:
            amount = self.budget * weights[actor] / denominator if denominator else Decimal("0")
            incentives.append(Incentive(actor, self.kind, Money(amount.quantize(Decimal("0.01")), self.currency), "按贡献分配激励预算", {"weight": str(weights[actor]), "denominator": str(denominator), "mechanism": outcome.mechanism, "run_id": context.run_id}))
        return tuple(incentives)


class IdempotentTransactionProcessor(TransactionProcessor):
    """Record pricing outcomes once and expose deterministic partial failures."""

    def __init__(self, delivery_check: Callable[[str], bool] | None = None):
        self.delivery_check = delivery_check or (lambda product_id: True); self._records: dict[str, TransactionRecord] = {}

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("transaction.idempotent", "1.0.0", "data_market", "transaction_processor", capabilities=("idempotency", "delivery_check", "partial_failure"))

    def execute(self, outcome: PricingOutcome, context: RunContext) -> TransactionRecord:
        payload = {"mechanism": outcome.mechanism, "allocations": [_canonical(allocation.__dict__) for allocation in outcome.allocations], "payments": [_canonical(payment.__dict__) for payment in outcome.payments]}
        transaction_id = f"tx-{canonical_sha256(payload)[:20]}"
        if transaction_id in self._records:
            return self._records[transaction_id]
        products = sorted({product_id for allocation in outcome.allocations for product_id in allocation.product_ids} | {product_id for payment in outcome.payments for product_id in payment.product_ids})
        failed_products = [product_id for product_id in products if not self.delivery_check(product_id)]
        status = "failed" if products and len(failed_products) == len(products) else "partial" if failed_products else "succeeded"
        record = TransactionRecord(transaction_id, outcome, status, diagnostics={"run_id": context.run_id, "products": tuple(products), "delivery_failures": tuple(failed_products), "idempotent": False})
        self._records[transaction_id] = record
        return record

    @property
    def records(self) -> tuple[TransactionRecord, ...]:
        return tuple(self._records.values())


def market_statistics(snapshot: MarketSnapshot) -> Mapping[str, Any]:
    """Return liquidity, seller concentration and participant composition facts."""
    active = [listing for listing in snapshot.listings if listing.status is ListingStatus.ACTIVE]; sellers = Counter(listing.seller_id for listing in active); total = sum(sellers.values()); shares = [(count / total) for count in sellers.values()] if total else []
    return {"active_listings": len(active), "seller_count": len(sellers), "seller_hhi": sum(share * share for share in shares), "participant_count": len(snapshot.participants), "participant_roles": dict(Counter(profile.role.value for profile in snapshot.participants)), "latest_mechanism": snapshot.latest_outcome.mechanism if snapshot.latest_outcome else None}


__all__ = ["rank_listings", "ReputationScore", "score_reputation", "ContributionIncentivePolicy", "IdempotentTransactionProcessor", "market_statistics"]
