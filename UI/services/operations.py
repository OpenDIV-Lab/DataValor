from __future__ import annotations

import math
from dataclasses import asdict, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from datavalor.core import RunContext

from .catalog import product_from_payload


def jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, Decimal)):
        return str(value)
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set)):
        return [jsonable(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def execute(operation: str, product_payload: dict, parameters: dict, run_id: str) -> tuple[Any, str]:
    product = product_from_payload(product_payload)
    records = product_payload.get("records", ())
    context = RunContext(run_id, seed=int(parameters.get("seed", 0)), config={"records": records})
    if operation == "profile":
        from datavalor.data_prof import BasicDataProfiler, ProfileRequest

        result = BasicDataProfiler().profile(
            product,
            ProfileRequest(
                fields=tuple(parameters.get("fields", ())),
                sample_size=parameters.get("sample_size"),
                include_examples=bool(parameters.get("include_examples", False)),
                options={"records": records},
            ),
            context,
        )
        return jsonable(result), BasicDataProfiler().spec.name
    if operation == "governance":
        from datavalor.data_gov import (
            LocalMetadataExtractor,
            RightsPolicyEvaluator,
            SensitiveFieldScanner,
        )

        metadata = LocalMetadataExtractor().inspect(product, context)
        report = RightsPolicyEvaluator().evaluate(product, parameters.get("operation", "analytics"), metadata, context)
        security = SensitiveFieldScanner().scan(product, parameters, context)
        result = jsonable(report)
        result["metadata"] = jsonable(metadata)
        result["security"] = jsonable(security)
        return result, RightsPolicyEvaluator().spec.name
    if operation == "evaluation":
        from .evaluation_workbench import run_evaluation

        result, producer = run_evaluation(product, records, parameters, context)
        return jsonable(result), producer
    if operation == "valuation":
        from .valuation_workbench import run_valuation

        result, producer = run_valuation(product, parameters, context)
        return jsonable(result), producer
    if operation == "pricing":
        from .pricing_workbench import run_pricing

        quote, normalized, trace, producer = run_pricing(product, parameters, context, record_count=len(records))
        result = jsonable(quote)
        result["normalized_parameters"] = jsonable(normalized)
        result["trace"] = jsonable(trace)
        return result, producer
    if operation == "market":
        from .market_workbench import run_market

        result, producer = run_market((product,), parameters, context)
        return jsonable(result), producer
    raise ValueError(f"unsupported operation: {operation}")


def execute_multiple(operation: str, product_payloads: list[dict], parameters: dict, run_id: str) -> tuple[Any, str]:
    """Execute a compatible operation over one or more products."""
    if len(product_payloads) == 1:
        return execute(operation, product_payloads[0], parameters, run_id)
    if operation != "market":
        raise ValueError(f"operation {operation} accepts one product")
    from .market_workbench import run_market

    products = tuple(product_from_payload(payload) for payload in product_payloads)
    context = RunContext(run_id, seed=int(parameters.get("seed", 0)), config={})
    result, producer = run_market(products, parameters, context)
    return jsonable(result), producer
