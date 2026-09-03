"""DataHub metadata connector mapped to DataValor's catalog contract.

The connector uses an injected emitter/client in tests and services.  When no
client is supplied it lazily resolves DataHub's documented ``DatahubRestEmitter``
and ``mce_builder`` helpers.  DataHub URNs/aspects never escape this module.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from datavalor.core import (
    CapabilityUnavailableError,
    ComponentSpec,
    DataProduct,
    RunContext,
    require_capability,
)
from datavalor.data_gov.interfaces import MetadataCatalog, MetadataExtractor
from datavalor.data_gov.models import CatalogQuery, FieldSchema, MetadataRecord

from ._connector import as_mapping, call_with_retry, mapping_value


def _record_from_mapping(value: Mapping[str, Any], product_id: str | None = None) -> MetadataRecord:
    fields_raw = mapping_value(value, "fields", "schema.fields", "schemaDefinition.columns", "editableProperties.fields", default=())
    fields = []
    if isinstance(fields_raw, Mapping):
        fields_raw = tuple(fields_raw.values())
    for item in fields_raw if isinstance(fields_raw, (list, tuple)) else ():
        item = as_mapping(item)
        name = mapping_value(item, "name", "fieldPath", "field_name")
        if name is None:
            continue
        fields.append(FieldSchema(str(name), str(mapping_value(item, "data_type", "type", "nativeDataType", default="unknown")),
                                  nullable=mapping_value(item, "nullable"), semantic_type=mapping_value(item, "semantic_type", "semanticType"),
                                  classification=mapping_value(item, "classification", "tags"), constraints=mapping_value(item, "constraints", default={}) or {},
                                  metadata=dict(item)))
    owner = mapping_value(value, "owner_id", "owner", "ownership.owner")
    if isinstance(owner, Mapping):
        owner = owner.get("name") or owner.get("id")
    product_name = mapping_value(value, "product_id", "productId", "name", "urn", default="unknown")
    return MetadataRecord(
        str(product_id or product_name), tuple(fields), owner_id=owner,
        source=mapping_value(value, "source", "platform", "dataPlatform"), license_id=mapping_value(value, "license_id", "license"),
        properties=dict(value),
    )


class DataHubMetadataCatalog(MetadataCatalog):
    def __init__(self, *, emitter: Any = None, client: Any = None, endpoint: str | None = None,
                 token: str | None = None, event_builder: Callable[..., Any] | None = None,
                 retries: int = 1, timeout: float = 10.0) -> None:
        self.emitter, self.client, self.endpoint, self.token = emitter, client, endpoint, token
        self.event_builder, self.retries, self.timeout = event_builder, retries, timeout

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("datahub.catalog", "0.1.0", "data_gov", "metadata_catalog",
                             capabilities=("metadata", "lineage", "ownership"), requires=("acryl-datahub>=0.13",))

    def _emitter(self) -> Any:
        if self.emitter is not None:
            return self.emitter
        datahub = require_capability("datahub", "datahub.emitter.rest_emitter", distribution="acryl-datahub", extra="governance")
        emitter_cls = getattr(datahub, "DatahubRestEmitter", None)
        if emitter_cls is None:
            raise RuntimeError("DataHub REST emitter is unavailable")
        return emitter_cls(gms_server=self.endpoint, token=self.token) if self.endpoint else emitter_cls()

    def _event(self, record: MetadataRecord) -> Any:
        if self.event_builder is not None:
            return self.event_builder(record)
        # An injected emitter is commonly a transport fake or a custom event
        # sink; a portable mapping is the least surprising payload for it.
        if self.emitter is not None:
            return {"product_id": record.product_id, "fields": [field.name for field in record.fields],
                    "owner_id": record.owner_id, "properties": dict(record.properties)}
        builder = require_capability("datahub_mce_builder", "datahub.emitter.mce_builder", distribution="acryl-datahub", extra="governance")
        urn_fn = getattr(builder, "make_dataset_urn", None)
        if not callable(urn_fn):
            raise RuntimeError("DataHub mce_builder has no make_dataset_urn function")
        urn = urn_fn(record.source or "datavalor", record.product_id)
        properties = {"datavalor.record": str(record.properties), "datavalor.owner": record.owner_id or ""}
        make_props = getattr(builder, "make_dataset_properties", None)
        if callable(make_props):
            try:
                aspect = make_props(urn=urn, customProperties=properties)
            except TypeError:
                aspect = make_props(customProperties=properties)
            try:
                mcp_module = require_capability("datahub_mcp", "datahub.emitter.mcp", distribution="acryl-datahub", extra="governance")
                wrapper = getattr(mcp_module, "MetadataChangeProposalWrapper", None)
                if callable(wrapper):
                    return wrapper(entityUrn=urn, aspect=aspect)
            except (CapabilityUnavailableError, TypeError, AttributeError):
                # Custom emitters may accept the aspect directly; the mapping
                # below remains useful for injected transports and dry runs.
                pass
            return {"entityUrn": urn, "aspect": aspect}
        return {"entityUrn": urn, "aspect": {"customProperties": properties}}

    def upsert(self, record: MetadataRecord, context: RunContext) -> MetadataRecord:
        emitter = self._emitter()
        event = self._event(record)
        method = getattr(emitter, "emit_mcp", None) or getattr(emitter, "emit_mce", None) or getattr(emitter, "emit", None)
        if not callable(method):
            raise RuntimeError("DataHub emitter exposes no emit_mcp/emit_mce/emit method")
        call_with_retry(method, event, retries=self.retries, timeout=self.timeout)
        return MetadataRecord(record.product_id, record.fields, record.owner_id, record.source, record.license_id,
                              record.lineage, {**record.properties, "connector": "datahub", "run_id": context.run_id})

    def get(self, product_id: str, context: RunContext) -> MetadataRecord | None:
        client = self.client
        if client is None:
            return None
        method = getattr(client, "get", None) or getattr(client, "get_metadata", None)
        if not callable(method):
            return None
        value = call_with_retry(method, product_id, retries=self.retries, timeout=self.timeout)
        return None if value is None else _record_from_mapping(as_mapping(value), product_id)

    def search(self, query: CatalogQuery, context: RunContext) -> tuple[MetadataRecord, ...]:
        client = self.client
        if client is None:
            return ()
        method = getattr(client, "search", None) or getattr(client, "search_metadata", None)
        if not callable(method):
            return ()
        values = call_with_retry(method, query.text or "", limit=query.limit, retries=self.retries, timeout=self.timeout)
        return tuple(_record_from_mapping(as_mapping(item)) for item in (values or ()) if as_mapping(item))


class DataHubMetadataExtractor(MetadataExtractor):
    """Create a DataValor metadata record from a product without contacting DataHub."""

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("datahub.extractor", "0.1.0", "data_gov", "metadata_extractor", requires=("acryl-datahub>=0.13",))

    def inspect(self, product: DataProduct, context: RunContext) -> MetadataRecord:
        fields = tuple(FieldSchema(str(name), "unknown") for name in product.metadata.get("fields", ()))
        return MetadataRecord(product.product_id, fields, product.owner_id, product.data.uri,
                              properties={"tags": product.tags, "version": product.version, "run_id": context.run_id})


__all__ = ["DataHubMetadataCatalog", "DataHubMetadataExtractor"]
