"""Typed extension registries for DataValue."""

from datavalor.core import Registry

from .interfaces import ContributionValuator, DataValuator, TrainableValuator, UtilityFunction

UTILITY_FUNCTIONS = Registry[UtilityFunction]("data_value.utilities")
VALUATORS = Registry[DataValuator]("data_value.valuators")
TRAINABLE_VALUATORS = Registry[TrainableValuator]("data_value.trainable_valuators")
CONTRIBUTION_VALUATORS = Registry[ContributionValuator]("data_value.contributions")

