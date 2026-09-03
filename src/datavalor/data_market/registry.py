"""Typed extension registries for DataMarket."""

from datavalor.core import Registry

from .interfaces import (
    IncentivePolicy,
    MarketCatalog,
    ParticipantRepository,
    RevenueAllocator,
    TransactionProcessor,
)
from .simulation import MarketSimulator, ParticipantStrategy

MARKET_CATALOGS = Registry[MarketCatalog]("data_market.catalogs")
PARTICIPANT_REPOSITORIES = Registry[ParticipantRepository]("data_market.participants")
INCENTIVE_POLICIES = Registry[IncentivePolicy]("data_market.incentives")
REVENUE_ALLOCATORS = Registry[RevenueAllocator]("data_market.revenue_allocators")
TRANSACTION_PROCESSORS = Registry[TransactionProcessor]("data_market.transactions")
PARTICIPANT_STRATEGIES = Registry[ParticipantStrategy]("data_market.strategies")
MARKET_SIMULATORS = Registry[MarketSimulator]("data_market.simulators")

