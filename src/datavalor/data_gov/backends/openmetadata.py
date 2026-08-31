"""OpenMetadata catalog connector.

The adapter accepts an injected REST/SDK client.  The default path lazily
constructs ``metadata.ingestion.ometa.ometa_api.OpenMetadata`` when available;
client-specific entities remain private to this boundary and are normalized to
DataValor metadata records.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from datavalor.core import ComponentSpec, DataProduct, RunContext, require_capability
from datavalor.data_gov.interfaces import MetadataCatalog, MetadataExtractor
from datavalor.data_gov.models import CatalogQuery, FieldSchema, MetadataRecord

from ._connector import as_mapping, call_with_retry, mapping_value
from .datahub import _record_from_mapping


class OpenMetadataCatalog(MetadataCatalog):
    def __init__(self, *, client: Any = None, server_url: str | None = None,
                 client_factory: Callable[..., Any] | None = None, retries: int = 1,
                 timeout: float = 10.0) -> None:
        self.client, self.server_url, self.client_factory = client, server_url, client_factory
        self.retries, self.timeout = retries, timeout

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("openmetadata.catalog", "0.1.0", "data_gov", "metadata_catalog",
                             capabilities=("catalog", "lineage", "governance"), requires=("openmetadata-ingestion>=1.5",))

    def _client(self) -> Any:
        if self.client is not None:
            return self.client
        if self.client_factory is not None:
            self.client = self.client_factory(self.server_url, self.timeout)
            return self.client
        ometa = require_capability("openmetadata", "metadata.ingestion.ometa.ometa_api", distribution="openmetadata-ingestion", extra="governance")
        cls = getattr(ometa, "OpenMetadata", None)
        if cls is None:
            raise RuntimeError("OpenMetadata SDK has no OpenMetadata client")
        config_cls = getattr(ometa, "OpenMetadataConnection", None)
        config = config_cls(hostPort=self.server_url) if config_cls and self.server_url else self.server_url
        self.client = cls(config)
        return self.client

    @staticmethod
    def _entity(record: MetadataRecord) -> dict[str, Any]:
        return {
            "name": record.product_id,
            "description": mapping_value(record.properties, "description", default=""),
            "owner": {"name": record.owner_id} if record.owner_id else None,
            "service": record.source,
            "schemaDefinition": {"columns": [{"name": field.name, "dataType": field.data_type,
                                                  "description": field.metadata.get("description", "")} for field in record.fields]},
            "extension": dict(record.properties),
        }

    def upsert(self, record: MetadataRecord, context: RunContext) -> MetadataRecord:
        client = self._client()
        entity = self._entity(record)
        method = getattr(client, "create_or_update", None) or getattr(client, "upsert", None)
        if not callable(method):
            raise RuntimeError("OpenMetadata client exposes no create_or_update/upsert method")
        try:
            call_with_retry(method, entity, retries=self.retries, timeout=self.timeout)
        except Exception:
            # Some SDK releases expect an entity object; an injected transport
            # can explicitly provide create_or_update(record, entity) instead.
            call_with_retry(method, record.product_id, entity, retries=self.retries, timeout=self.timeout)
        return MetadataRecord(record.product_id, record.fields, record.owner_id, record.source, record.license_id,
                              record.lineage, {**record.properties, "connector": "openmetadata", "run_id": context.run_id})

    def get(self, product_id: str, context: RunContext) -> MetadataRecord | None:
        client = self._client()
        method = getattr(client, "get_by_name", None) or getattr(client, "get", None)
        if not callable(method):
            return None
        value = call_with_retry(method, product_id, retries=self.retries, timeout=self.timeout)
        return None if value is None else _record_from_mapping(as_mapping(value), product_id)

    def search(self, query: CatalogQuery, context: RunContext) -> tuple[MetadataRecord, ...]:
        client = self._client()
        method = getattr(client, "search", None) or getattr(client, "es_search", None)
        if not callable(method):
            return ()
        value = call_with_retry(method, query.text or "", retries=self.retries, timeout=self.timeout)
        if isinstance(value, Mapping):
            value = value.get("hits", value.get("data", ()))
        return tuple(_record_from_mapping(as_mapping(item)) for item in (value or ()) if as_mapping(item))


class OpenMetadataExtractor(MetadataExtractor):
    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("openmetadata.extractor", "0.1.0", "data_gov", "metadata_extractor",
                             requires=("openmetadata-ingestion>=1.5",))

    def inspect(self, product: DataProduct, context: RunContext) -> MetadataRecord:
        fields = tuple(FieldSchema(str(name), "unknown") for name in product.metadata.get("fields", ()))
        return MetadataRecord(product.product_id, fields, product.owner_id, product.data.uri,
                              properties={"tags": product.tags, "version": product.version, "run_id": context.run_id})


__all__ = ["OpenMetadataCatalog", "OpenMetadataExtractor"]
