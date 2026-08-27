"""Framework-neutral boundary for an optional research Web UI."""

from .interfaces import ViewProvider, WebApplicationFactory
from .models import ActionSpec, ApplicationSpec, ViewModel, ViewSpec
from .registry import VIEW_PROVIDERS, WEB_APPLICATION_FACTORIES

__all__ = [
    "VIEW_PROVIDERS",
    "WEB_APPLICATION_FACTORIES",
    "ActionSpec",
    "ApplicationSpec",
    "ViewModel",
    "ViewProvider",
    "ViewSpec",
    "WebApplicationFactory",
]
