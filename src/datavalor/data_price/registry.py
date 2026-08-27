"""Typed extension registries for DataPrice."""

from datavalor.core import Registry

from .interfaces import OnlinePricingModel, PriceConstraint, PricingMechanism, PricingModel

PRICING_MODELS = Registry[PricingModel]("data_price.models")
ONLINE_PRICING_MODELS = Registry[OnlinePricingModel]("data_price.online_models")
PRICE_CONSTRAINTS = Registry[PriceConstraint]("data_price.constraints")
PRICING_MECHANISMS = Registry[PricingMechanism]("data_price.mechanisms")

