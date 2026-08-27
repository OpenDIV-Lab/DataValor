"""Exception hierarchy shared by all DataValor modules."""


class DataValorError(Exception):
    """Base exception for errors raised through public DataValor interfaces."""


class ConfigurationError(DataValorError):
    """A component or pipeline configuration is invalid."""


class CapabilityUnavailableError(DataValorError):
    """A requested optional capability is not installed or cannot be used."""


class RegistryError(DataValorError):
    """Base class for component registry failures."""


class DuplicateComponentError(RegistryError):
    """A component name is already registered in a registry."""


class ComponentNotFoundError(RegistryError):
    """A requested component is not registered."""


class RegistryFrozenError(RegistryError):
    """A frozen registry cannot be mutated."""


class ContractError(DataValorError):
    """An input, output, or artifact violates a public contract."""


class PolicyDeniedError(DataValorError):
    """A governance or access policy denied an operation."""

