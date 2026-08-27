"""Typed extension registries for optional Web UI components."""

from datavalor.core import Registry

from .interfaces import ViewProvider, WebApplicationFactory

VIEW_PROVIDERS = Registry[ViewProvider]("toolkit.webui.views")
WEB_APPLICATION_FACTORIES = Registry[WebApplicationFactory]("toolkit.webui.apps")

