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
        from datavalor.data_eval import (
            CompletenessMetric,
            CompositeEvaluator,
            DuplicateRateMetric,
            EvaluationRequest,
            FieldValidityMetric,
        )

        request = EvaluationRequest(
            metrics=("basic.completeness", "basic.duplicate_rate", "basic.field_validity"),
            options={
                "records": records,
                "required_fields": tuple(parameters.get("required_fields", ())),
                "field_types": parameters.get("field_types", {}),
            },
        )
        evaluator = CompositeEvaluator()
        result = evaluator.evaluate(
            product,
            request,
            (CompletenessMetric(), DuplicateRateMetric(), FieldValidityMetric()),
            context,
        )
        return jsonable(result), evaluator.spec.name
    if operation == "valuation":
        from datavalor.core import DataScope
        from datavalor.data_value import (
            ValuationRequest,
            ValuationTarget,
            WeightedUserTaskValuator,
        )

        valuator = WeightedUserTaskValuator(
            base_value=float(parameters.get("base_value", 1000)),
            currency=str(parameters.get("currency", "CNY")),
        )
        request = ValuationRequest(
            product,
            (ValuationTarget(product.product_id, product.product_id, DataScope.PRODUCT),),
            rights=product.rights,
            options={"evaluation_vector": parameters.get("evaluation_vector", {})},
        )
        return jsonable(valuator.value(request, context)), valuator.spec.name
    if operation == "pricing":
        from datavalor.data_price import PRICING_MODELS, QuoteRequest

        model_name = str(parameters.get("model", "pricing.quality_freshness"))
        if model_name not in PRICING_MODELS:
            raise ValueError(f"pricing model is not supported by the workbench: {model_name}")
        model = PRICING_MODELS.create(model_name)
        market_context = {
            "candidate_prices": (50000, 75000, 100000, 125000),
            "usage": len(records),
            "period_fee": parameters.get("base_price", 0),
            "included_usage": 100,
            "overage_unit_price": 1,
            "std_error": parameters.get("value_std_error", 0),
            "rights_factor": 1,
            "cost_floor": parameters.get("preparation_cost", 0),
            "seller_share": 0.6,
            "confidence": 0.9,
            "age_days": 1,
            "previous_price": parameters.get("base_price", 0),
            "incremental_coverage": 0.2,
            "quality_gain": 0.1,
            "volume_growth": 0.1,
            **{key: value for key, value in parameters.items() if key not in {"model", "seed"}},
        }
        quote = model.quote(QuoteRequest(product, rights=product.rights, market_context=market_context), context)
        return jsonable(quote), model.spec.name
    if operation == "market":
        from datavalor.data_market import MarketGapAnalyzer
        from datavalor.data_price import (
            Ask,
            Bid,
            BudgetFeasibleProcurement,
            FirstPriceAuction,
            McAfeeDoubleAuction,
            Money,
            PricingRequest,
            SecondPriceAuction,
            VCGMechanism,
            evaluate_pricing_properties,
        )

        currency = str(parameters.get("currency", "CNY"))
        bids = tuple(
            Bid(
                f"bid-{index + 1}",
                str(item.get("buyer_id", f"buyer-{index + 1}")),
                (product.product_id,),
                Money(Decimal(str(item.get("amount", 0))), currency),
                Decimal(str(item.get("quantity", 1))),
                task_id=item.get("task_id"),
                constraints=item.get("constraints", {}),
                metadata=item.get("metadata", {}),
            )
            for index, item in enumerate(parameters.get("bids", ()))
        )
        asks = tuple(
            Ask(
                f"ask-{index + 1}",
                str(item.get("seller_id", f"seller-{index + 1}")),
                (product.product_id,),
                Money(Decimal(str(item.get("reserve", 0))), currency),
                Decimal(str(item.get("quantity", 1))),
                constraints=item.get("constraints", {}),
                metadata=item.get("metadata", {}),
            )
            for index, item in enumerate(parameters.get("asks", ()))
        )
        mechanisms = {
            "first_price_auction": FirstPriceAuction,
            "second_price_auction": SecondPriceAuction,
            "vcg": VCGMechanism,
            "mcafee_double_auction": McAfeeDoubleAuction,
            "budget_feasible_procurement": BudgetFeasibleProcurement,
        }
        mechanism_name = str(parameters.get("mechanism", "mcafee_double_auction"))
        if mechanism_name not in mechanisms:
            raise ValueError(f"market mechanism is not supported by the workbench: {mechanism_name}")
        request = PricingRequest(
            (product,),
            bids,
            asks,
            supply={product.product_id: Decimal(str(parameters.get("supply", sum((ask.quantity for ask in asks), Decimal("0")))))},
            demand={product.product_id: sum((bid.quantity for bid in bids), Decimal("0"))},
            market_context={key: value for key, value in parameters.items() if key not in {"bids", "asks", "mechanism"}},
        )
        mechanism = mechanisms[mechanism_name]()
        outcome = mechanism.price(request, context)
        budgets = {str(item.get("buyer_id")): Decimal(str(item["budget"])) for item in parameters.get("bids", ()) if item.get("budget") is not None}
        result = {
            "outcome": jsonable(outcome),
            "properties": jsonable(evaluate_pricing_properties(outcome, request, budgets=budgets or None)),
            "gaps": jsonable(MarketGapAnalyzer().analyze(bids, asks)),
            "order_book": {
                "bids": jsonable(sorted(bids, key=lambda item: item.amount.amount, reverse=True)),
                "asks": jsonable(sorted(asks, key=lambda item: item.reserve.amount)),
            },
        }
        return result, mechanism.name
    raise ValueError(f"unsupported operation: {operation}")
