from __future__ import annotations

from datetime import datetime
from typing import Any

from datavalor.core import DataProduct, DataReference, RightsBundle


def product_from_payload(payload: dict[str, Any]) -> DataProduct:
    data = payload.get("data", {})
    rights = payload.get("rights", {})
    valid_until = rights.get("valid_until")
    return DataProduct(
        product_id=payload["product_id"],
        title=payload.get("title", payload["product_id"]),
        data=DataReference(
            uri=data.get("uri", f"memory://{payload['product_id']}"),
            format=data.get("format", "records"),
            media_type=data.get("media_type"),
            checksum=data.get("checksum"),
            schema_ref=data.get("schema_ref"),
            record_count=data.get("record_count"),
            metadata=data.get("metadata", {}),
        ),
        owner_id=payload.get("owner_id", "local-owner"),
        version=str(payload.get("version", "1")),
        description=payload.get("description", ""),
        rights=RightsBundle(
            purposes=tuple(rights.get("purposes", ())),
            commercial_use=rights.get("commercial_use"),
            redistribution=rights.get("redistribution"),
            exclusivity=rights.get("exclusivity"),
            valid_until=datetime.fromisoformat(valid_until) if valid_until else None,
            jurisdictions=tuple(rights.get("jurisdictions", ())),
            constraints=rights.get("constraints", {}),
        ),
        tags=tuple(payload.get("tags", ())),
        metadata=payload.get("metadata", {}),
    )
