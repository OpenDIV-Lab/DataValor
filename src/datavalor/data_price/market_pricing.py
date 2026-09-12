"""Explainable market-facing pricing built on the stable quote contracts."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Mapping, Sequence

from datavalor.core import ComponentSpec, RightsBundle

from .interfaces import PriceConstraint, PricingModel
from .models import Money, PriceQuote
from .pricing_models import _expiry

_CENT = Decimal("0.01")


def _decimal(value: Any, default: str = "0") -> Decimal:
    try:
        result = Decimal(str(value))
    except Exception:
        return Decimal(default)
    return result if result.is_finite() else Decimal(default)


def _unit(value: Any, default: str = "0") -> Decimal:
    return min(Decimal("1"), max(Decimal("0"), _decimal(value, default)))


def _money(value: Decimal, currency: str) -> Money:
    return Money(max(Decimal("0"), value).quantize(_CENT, rounding=ROUND_HALF_UP), currency)


class PriceRangePricingModel(PricingModel):
    """Quote a target while retaining defensible floor and ceiling values."""

    @property
    def spec(self):
        return ComponentSpec("pricing.price_range", "1.0.0", "data_price", "pricing_model", capabilities=("valuation", "range", "cost_floor", "comparable"))

    def quote(self, request, context):
        ctx = request.market_context
        estimated = max(Decimal("0"), _decimal(ctx.get("estimated_value")))
        uncertainty = max(Decimal("0"), _decimal(ctx.get("value_std_error")))
        cost_floor = max(Decimal("0"), _decimal(ctx.get("cost_floor")))
        seller_share = _unit(ctx.get("seller_share", "0.5"), "0.5")
        confidence = _unit(ctx.get("confidence", "1"), "1")
        comparable = max(Decimal("0"), _decimal(ctx.get("comparable_price")))
        comparable_weight = _unit(ctx.get("comparable_weight", "0.25"), "0.25") if comparable else Decimal("0")
        value_target = estimated * seller_share * confidence
        target = value_target * (Decimal("1") - comparable_weight) + comparable * comparable_weight
        risk_width = Decimal("1.96") * uncertainty * seller_share
        floor = max(cost_floor, target - risk_width)
        ceiling = max(floor, min(estimated, target + risk_width) if estimated else target + risk_width)
        target = min(ceiling, max(floor, target))
        currency = str(ctx.get("currency", "CNY"))
        components = {"estimated_value": estimated, "value_std_error": uncertainty, "seller_share": seller_share, "confidence": confidence, "cost_floor": cost_floor, "comparable_price": comparable, "comparable_weight": comparable_weight, "floor": floor, "target": target, "ceiling": ceiling}
        return PriceQuote(f"range-{context.run_id}", request.product.product_id, _money(target, currency), self.spec.name, request.buyer.actor_id if request.buyer else None, request.rights or request.product.rights, _expiry(request, context), components, {"run_id": context.run_id, "interval": "valuation_uncertainty_95"})


@dataclass(frozen=True)
class ComparableMatch:
    comparable_id: str
    similarity: float
    price: Money
    attributes: Mapping[str, Any] = field(default_factory=dict)


class ComparableSelector:
    """Select comparable products using explicit numeric/categorical features."""

    def select(self, target: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]], *, feature_weights: Mapping[str, float] | None = None, limit: int = 5, currency: str = "CNY") -> tuple[ComparableMatch, ...]:
        if limit < 0:
            raise ValueError("limit must be non-negative")
        weights = dict(feature_weights or {name: 1.0 for name in target})
        matches = []
        for index, candidate in enumerate(candidates):
            if str(candidate.get("currency", currency)) != currency:
                continue
            total = score = 0.0
            for name, weight_value in weights.items():
                weight = max(0.0, float(weight_value))
                if weight == 0 or name not in target or name not in candidate:
                    continue
                left, right = target[name], candidate[name]
                if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                    left_number, right_number = float(left), float(right)
                    if not math.isfinite(left_number) or not math.isfinite(right_number):
                        similarity = 0.0
                    else:
                        scale = max(abs(left_number), abs(right_number), 1e-12)
                        similarity = max(0.0, 1.0 - abs(left_number - right_number) / scale)
                else:
                    similarity = 1.0 if left == right else 0.0
                score += weight * similarity; total += weight
            similarity = score / total if total else 0.0
            price = _money(max(Decimal("0"), _decimal(candidate.get("price"))), currency)
            matches.append(ComparableMatch(str(candidate.get("comparable_id", index)), similarity, price, dict(candidate)))
        matches.sort(key=lambda item: (-item.similarity, item.comparable_id))
        return tuple(matches[:limit])


class ComparablePricingModel(PricingModel):
    """Form a quote from similarity-weighted market comparables."""

    @property
    def spec(self):
        return ComponentSpec("pricing.comparable", "1.0.0", "data_price", "pricing_model", capabilities=("comparable", "benchmark", "adjustment"))

    def quote(self, request, context):
        ctx = request.market_context; currency = str(ctx.get("currency", "CNY"))
        matches = ComparableSelector().select(ctx.get("target_attributes", {}), tuple(ctx.get("comparables", ())), feature_weights=ctx.get("feature_weights"), limit=int(ctx.get("comparable_limit", 5)), currency=currency)
        usable = [item for item in matches if item.similarity > 0]
        if not usable:
            raise ValueError("no positive-similarity comparable prices")
        denominator = sum(Decimal(str(item.similarity)) for item in usable)
        benchmark = sum(item.price.amount * Decimal(str(item.similarity)) for item in usable) / denominator
        quality = max(Decimal("0"), _decimal(ctx.get("quality_ratio", 1), "1"))
        freshness = max(Decimal("0"), _decimal(ctx.get("freshness_ratio", 1), "1"))
        rights = max(Decimal("0"), _decimal(ctx.get("rights_ratio", 1), "1"))
        adjusted = benchmark * quality * freshness * rights
        floor = max(Decimal("0"), _decimal(ctx.get("floor")))
        ceiling = max(floor, _decimal(ctx.get("ceiling", adjusted), str(adjusted)))
        total = min(ceiling, max(floor, adjusted))
        components = {"benchmark_price": benchmark, "quality_ratio": quality, "freshness_ratio": freshness, "rights_ratio": rights, "floor": floor, "ceiling": ceiling}
        diagnostics = {"run_id": context.run_id, "comparables": tuple({"id": item.comparable_id, "similarity": item.similarity, "price": str(item.price.amount)} for item in usable)}
        return PriceQuote(f"comparable-{context.run_id}", request.product.product_id, _money(total, currency), self.spec.name, request.buyer.actor_id if request.buyer else None, request.rights or request.product.rights, _expiry(request, context), components, diagnostics)


def _rights_breadth(rights: RightsBundle, now: datetime) -> Mapping[str, Decimal]:
    expiry = rights.valid_until
    if expiry is not None and expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    duration_years = Decimal("5") if expiry is None else min(Decimal("5"), max(Decimal("0"), Decimal(str((expiry - now).total_seconds() / 31557600.0))))
    return {"commercial": Decimal("1") if rights.commercial_use is True else Decimal("0"), "redistribution": Decimal("1") if rights.redistribution is True else Decimal("0"), "exclusive": Decimal("1") if rights.exclusivity not in {None, "none", "non_exclusive"} else Decimal("0"), "jurisdictions": Decimal(len(rights.jurisdictions)), "duration_years": duration_years}


class RightsDifferentiatedPricingModel(PricingModel):
    """Apply monotone premiums for explicitly broader requested rights."""

    @property
    def spec(self):
        return ComponentSpec("pricing.rights_differentiated", "1.0.0", "data_price", "pricing_model", capabilities=("rights", "monotone", "differentiated"))

    def quote(self, request, context):
        ctx = request.market_context; base = max(Decimal("0"), _decimal(ctx.get("base_price")))
        rights = request.rights or request.product.rights
        now = context.started_at if context.started_at.tzinfo else context.started_at.replace(tzinfo=timezone.utc)
        breadth = _rights_breadth(rights, now)
        rates = {"commercial": _decimal(ctx.get("commercial_premium", "0.20")), "redistribution": _decimal(ctx.get("redistribution_premium", "0.30")), "exclusive": _decimal(ctx.get("exclusivity_premium", "0.50")), "jurisdictions": _decimal(ctx.get("per_jurisdiction_premium", "0.02")), "duration_years": _decimal(ctx.get("per_year_premium", "0.05"))}
        premiums = {name: max(Decimal("0"), breadth[name] * rates[name]) for name in breadth}
        multiplier = Decimal("1") + sum(premiums.values(), Decimal("0")); total = base * multiplier
        currency = str(ctx.get("currency", "CNY"))
        return PriceQuote(f"rights-{context.run_id}", request.product.product_id, _money(total, currency), self.spec.name, request.buyer.actor_id if request.buyer else None, rights, _expiry(request, context), {"base_price": base, "rights_multiplier": multiplier, **{f"{name}_premium": value for name, value in premiums.items()}}, {"run_id": context.run_id, "rights_breadth": breadth})


class FreshnessTierPricingModel(PricingModel):
    """Apply the first matching age tier to a base price."""

    def __init__(self, tiers: Sequence[Sequence[Any]] = ((1, "1.20"), (7, "1.00"), (30, "0.80"), (math.inf, "0.50")), currency: str = "CNY"):
        normalized = tuple((Decimal("Infinity") if bound == math.inf else _decimal(bound), max(Decimal("0"), _decimal(factor))) for bound, factor in tiers)
        if not normalized or any(bound < 0 for bound, _ in normalized) or any(left[0] >= right[0] for left, right in zip(normalized, normalized[1:])):
            raise ValueError("freshness tiers require increasing non-negative bounds")
        if normalized[-1][0].is_finite():
            normalized += ((Decimal("Infinity"), normalized[-1][1]),)
        self.tiers, self.currency = normalized, currency

    @property
    def spec(self):
        return ComponentSpec("pricing.freshness_tier", "1.0.0", "data_price", "pricing_model", capabilities=("freshness", "tiered", "time"))

    def quote(self, request, context):
        age = max(Decimal("0"), _decimal(request.market_context.get("age_days"))); base = max(Decimal("0"), _decimal(request.market_context.get("base_price")))
        bound, factor = next((tier for tier in self.tiers if age <= tier[0]), self.tiers[-1])
        currency = str(request.market_context.get("currency", self.currency))
        return PriceQuote(f"freshness-{context.run_id}", request.product.product_id, _money(base * factor, currency), self.spec.name, request.buyer.actor_id if request.buyer else None, request.rights or request.product.rights, _expiry(request, context), {"base_price": base, "age_days": age, "tier_upper_days": bound, "freshness_factor": factor}, {"run_id": context.run_id})


class VersionDeltaPricingModel(PricingModel):
    """Price a new version from its incremental coverage and quality gain."""

    @property
    def spec(self):
        return ComponentSpec("pricing.version_delta", "1.0.0", "data_price", "pricing_model", capabilities=("version", "incremental", "coverage"))

    def quote(self, request, context):
        ctx = request.market_context; previous = max(Decimal("0"), _decimal(ctx.get("previous_price")))
        incremental = _unit(ctx.get("incremental_coverage")); quality_gain = max(Decimal("-1"), min(Decimal("1"), _decimal(ctx.get("quality_gain"))))
        volume_growth = max(Decimal("-1"), _decimal(ctx.get("volume_growth")))
        weights = {"coverage": max(Decimal("0"), _decimal(ctx.get("coverage_weight", "0.5"))), "quality": max(Decimal("0"), _decimal(ctx.get("quality_weight", "0.3"))), "volume": max(Decimal("0"), _decimal(ctx.get("volume_weight", "0.2")))}
        delta_factor = weights["coverage"] * incremental + weights["quality"] * quality_gain + weights["volume"] * volume_growth
        floor_factor = max(Decimal("0"), _decimal(ctx.get("minimum_factor", "0")))
        factor = max(floor_factor, Decimal("1") + delta_factor)
        currency = str(ctx.get("currency", "CNY"))
        return PriceQuote(f"version-{context.run_id}", request.product.product_id, _money(previous * factor, currency), self.spec.name, request.buyer.actor_id if request.buyer else None, request.rights or request.product.rights, _expiry(request, context), {"previous_price": previous, "incremental_coverage": incremental, "quality_gain": quality_gain, "volume_growth": volume_growth, "delta_factor": delta_factor, "version_factor": factor}, {"run_id": context.run_id, "weights": weights, "product_version": request.product.version})


class BundleDiscountConstraint(PriceConstraint):
    """Project bundle quotes for overlap discounts and complement premiums."""

    @property
    def spec(self):
        return ComponentSpec("constraint.bundle_overlap", "1.0.0", "data_price", "price_constraint", capabilities=("bundle", "overlap", "complementarity"))

    def project(self, quotes, context):
        if not quotes:
            return ()
        currencies = {quote.price.currency for quote in quotes}
        if len(currencies) != 1:
            raise ValueError("bundle quotes must use one currency")
        overlap = _unit(context.config.get("overlap_ratio")); complementarity = _unit(context.config.get("complementarity"))
        overlap_weight = _unit(context.config.get("overlap_discount_weight", "1"), "1")
        premium_weight = max(Decimal("0"), _decimal(context.config.get("complementarity_premium_weight", "0")))
        factor = max(Decimal("0"), Decimal("1") - overlap * overlap_weight + complementarity * premium_weight)
        total = sum((quote.price.amount for quote in quotes), Decimal("0")); adjusted_total = total * factor
        result = []
        for quote in quotes:
            share = quote.price.amount / total if total else Decimal("1") / Decimal(len(quotes))
            adjusted = adjusted_total * share
            result.append(PriceQuote(quote.quote_id, quote.product_id, _money(adjusted, quote.price.currency), quote.pricing_model, quote.buyer_id, quote.rights, quote.valid_until, {**quote.components, "bundle_original_price": quote.price.amount, "bundle_factor": factor}, {**quote.diagnostics, "bundle_projected": True, "overlap_ratio": overlap, "complementarity": complementarity, "bundle_original_total": total, "bundle_adjusted_total": adjusted_total}))
        return tuple(result)


@dataclass(frozen=True)
class QuoteAuditFinding:
    quote_id: str
    code: str
    severity: str
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class QuoteAuditReport:
    status: str
    findings: tuple[QuoteAuditFinding, ...]
    checked_quotes: int
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


def audit_price_quotes(quotes: Sequence[PriceQuote], contexts: Mapping[str, Mapping[str, Any]] | None = None, *, evaluated_at: datetime | None = None, max_value_ratio: Decimal | float = Decimal("1"), max_jump_ratio: Decimal | float = Decimal("0.5")) -> QuoteAuditReport:
    """Audit cost, valuation, expiry, jumps, and rights-price monotonicity."""
    contexts = contexts or {}; now = evaluated_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    findings = []
    for quote in quotes:
        ctx = contexts.get(quote.quote_id, {}); amount = quote.price.amount
        cost = max(Decimal("0"), _decimal(ctx.get("cost_floor")))
        estimated = max(Decimal("0"), _decimal(ctx.get("estimated_value")))
        previous = max(Decimal("0"), _decimal(ctx.get("previous_price")))
        if amount < cost:
            findings.append(QuoteAuditFinding(quote.quote_id, "price.below_cost", "high", "报价低于声明成本底价", {"price": amount, "cost_floor": cost}))
        if estimated and amount > estimated * _decimal(max_value_ratio, "1"):
            findings.append(QuoteAuditFinding(quote.quote_id, "price.above_value_ratio", "medium", "报价超过允许的估值比例", {"price": amount, "estimated_value": estimated}))
        if previous and abs(amount - previous) / previous > _decimal(max_jump_ratio, "0.5"):
            findings.append(QuoteAuditFinding(quote.quote_id, "price.jump", "medium", "报价相对上一价格跳变过大", {"price": amount, "previous_price": previous}))
        if quote.valid_until is not None:
            expiry = quote.valid_until if quote.valid_until.tzinfo else quote.valid_until.replace(tzinfo=timezone.utc)
            if expiry <= now:
                findings.append(QuoteAuditFinding(quote.quote_id, "quote.expired", "high", "报价已过期"))
    for left_index, left in enumerate(quotes):
        for right in quotes[left_index + 1:]:
            if left.product_id != right.product_id or left.price.currency != right.price.currency or not left.rights or not right.rights:
                continue
            left_breadth = _rights_breadth(left.rights, now); right_breadth = _rights_breadth(right.rights, now)
            left_dominates = all(left_breadth[name] >= right_breadth[name] for name in left_breadth) and any(left_breadth[name] > right_breadth[name] for name in left_breadth)
            right_dominates = all(right_breadth[name] >= left_breadth[name] for name in left_breadth) and any(right_breadth[name] > left_breadth[name] for name in left_breadth)
            if left_dominates and left.price.amount < right.price.amount:
                findings.append(QuoteAuditFinding(left.quote_id, "rights.non_monotone_price", "high", "更宽权利的报价低于较窄权利", {"narrower_quote_id": right.quote_id}))
            elif right_dominates and right.price.amount < left.price.amount:
                findings.append(QuoteAuditFinding(right.quote_id, "rights.non_monotone_price", "high", "更宽权利的报价低于较窄权利", {"narrower_quote_id": left.quote_id}))
    status = "invalid" if any(item.severity == "high" for item in findings) else "review" if findings else "valid"
    return QuoteAuditReport(status, tuple(findings), len(quotes), {"evaluated_at": now.isoformat(), "max_value_ratio": str(max_value_ratio), "max_jump_ratio": str(max_jump_ratio)})


__all__ = ["BundleDiscountConstraint", "ComparableMatch", "ComparablePricingModel", "ComparableSelector", "FreshnessTierPricingModel", "PriceRangePricingModel", "QuoteAuditFinding", "QuoteAuditReport", "RightsDifferentiatedPricingModel", "VersionDeltaPricingModel", "audit_price_quotes"]
