"""Synchronous, persisted batch execution for the local workbench."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

from .operations import execute, execute_multiple, jsonable
from .workspace import Workspace


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_metrics(operation: str, result: dict[str, Any], metrics: dict[str, Any]) -> None:
    if operation == "governance":
        metrics["rights_decision"] = result.get("decision", "unknown")
    elif operation == "profile":
        metrics["record_count"] = result.get("record_count", metrics.get("record_count"))
        metrics["field_count"] = len(result.get("fields", ()))
    elif operation == "evaluation":
        values = []
        for item in result.get("metrics", ()):
            if not isinstance(item, dict):
                continue
            value = _number(item.get("value"))
            if value is None or not 0 <= value <= 1:
                continue
            direction = item.get("direction")
            if direction == "higher_is_better":
                values.append(value)
            elif direction == "lower_is_better":
                values.append(1 - value)
        if values:
            metrics["quality_score"] = round(sum(values) / len(values), 4)
    elif operation == "valuation":
        estimates = result.get("estimates", ())
        if estimates:
            metrics["value"] = _number(estimates[0].get("value"))
            metrics["value_currency"] = estimates[0].get("currency", "CNY")
    elif operation == "pricing":
        price = result.get("price", {})
        metrics["price"] = _number(price.get("amount"))
        metrics["price_currency"] = price.get("currency", "CNY")


def _persist_stage(
    workspace: Workspace,
    *,
    batch_id: str,
    product_id: str,
    operation: str,
    result: dict[str, Any],
    producer: str,
    started_at: str,
    duration_ms: int,
    input_artifact_ids: list[str] | None = None,
    input_run_ids: list[str] | None = None,
) -> tuple[str, str]:
    suffix = uuid.uuid4().hex[:10]
    artifact_id = f"artifact-{suffix}"
    run_id = f"run-{suffix}"
    finished_at = _now()
    workspace.put(
        "artifacts",
        artifact_id,
        {
            "artifact_id": artifact_id,
            "kind": operation,
            "producer": producer,
            "batch_id": batch_id,
            "product_id": product_id,
            "payload": result,
            "created_at": finished_at,
        },
    )
    workspace.put(
        "runs",
        run_id,
        {
            "run_id": run_id,
            "batch_id": batch_id,
            "operation": operation,
            "product_id": product_id,
            "product_ids": [product_id],
            "status": "succeeded",
            "artifact_id": artifact_id,
            "producer": producer,
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_ms": duration_ms,
            "input_artifact_ids": list(input_artifact_ids or ()),
            "input_run_ids": list(input_run_ids or ()),
        },
    )
    return run_id, artifact_id


def _status(succeeded: int, failed: int) -> str:
    if failed == 0:
        return "succeeded"
    return "partial" if succeeded else "failed"


def execute_batch(
    workspace: Workspace,
    *,
    product_ids: list[str],
    operations: list[str],
    parameters: dict[str, dict[str, Any]] | None = None,
    label: str = "Untitled batch",
    scenario_id: str | None = None,
    seed: int = 0,
    fail_fast: bool = False,
    input_artifact_ids: list[str] | None = None,
    include_related_content: bool = True,
) -> dict[str, Any]:
    """Run product stages plus an optional market stage and persist every result."""
    if not product_ids:
        raise ValueError("batch requires at least one product")
    if not operations:
        raise ValueError("batch requires at least one operation")
    products = [workspace.get("products", product_id) for product_id in product_ids]
    missing = [product_id for product_id, product in zip(product_ids, products) if product is None]
    if missing:
        raise ValueError(f"products not found: {', '.join(missing)}")
    input_artifact_ids = list(dict.fromkeys(input_artifact_ids or ()))
    input_run_ids: list[str] = []
    if include_related_content:
        selected_product_ids = set(product_ids)
        related_artifact_ids = [
            artifact.get("artifact_id")
            for artifact in workspace.list("artifacts")
            if artifact.get("artifact_id")
            and (
                artifact.get("product_id") in selected_product_ids
                or selected_product_ids.intersection(artifact.get("product_ids", ()))
            )
        ]
        input_artifact_ids = list(dict.fromkeys([*input_artifact_ids, *related_artifact_ids]))
        input_run_ids = [
            run.get("run_id")
            for run in workspace.list("runs")
            if run.get("run_id")
            and (
                run.get("product_id") in selected_product_ids
                or selected_product_ids.intersection(run.get("product_ids", ()))
            )
        ]
    missing_artifacts = [
        artifact_id
        for artifact_id in input_artifact_ids
        if workspace.get("artifacts", artifact_id) is None
    ]
    if missing_artifacts:
        raise ValueError(f"input artifacts not found: {', '.join(missing_artifacts)}")

    parameters = parameters or {}
    batch_id = f"batch-{uuid.uuid4().hex[:12]}"
    started_at = _now()
    items: list[dict[str, Any]] = []
    succeeded_stages = 0
    failed_stages = 0
    product_operations = [operation for operation in operations if operation != "market"]

    for product_id, product in zip(product_ids, products):
        item = {
            "product_id": product_id,
            "title": product.get("title", product_id),
            "status": "queued",
            "metrics": {
                "record_count": product.get("data", {}).get("record_count", len(product.get("records", ()))),
                "quality_signal": product.get("metadata", {}).get("quality"),
                "freshness": product.get("metadata", {}).get("freshness"),
                "asking_price": product.get("metadata", {}).get("asking_price"),
                "asking_price_currency": product.get("metadata", {}).get("currency", "CNY"),
            },
            "stages": [],
        }
        item_succeeded = 0
        item_failed = 0
        for operation in product_operations:
            stage_started = _now()
            tick = time.perf_counter()
            run_id = f"{batch_id}-{product_id}-{operation}"
            operation_parameters = dict(parameters.get(operation, {}))
            if operation == "valuation":
                signal_names = operation_parameters.pop("product_signals", ())
                evaluation_vector = dict(operation_parameters.get("evaluation_vector", {}))
                for signal_name in signal_names:
                    signal = product.get("metadata", {}).get(str(signal_name))
                    if signal is not None:
                        evaluation_vector[f"product_{signal_name}"] = signal
                operation_parameters["evaluation_vector"] = evaluation_vector
            operation_parameters.setdefault("seed", seed)
            try:
                result, producer = execute(operation, product, operation_parameters, run_id)
                result = jsonable(result)
                duration_ms = max(0, round((time.perf_counter() - tick) * 1000))
                persisted_run, artifact_id = _persist_stage(
                    workspace,
                    batch_id=batch_id,
                    product_id=product_id,
                    operation=operation,
                    result=result,
                    producer=producer,
                    started_at=stage_started,
                    duration_ms=duration_ms,
                    input_artifact_ids=input_artifact_ids,
                    input_run_ids=input_run_ids,
                )
                item["stages"].append(
                    {
                        "operation": operation,
                        "status": "succeeded",
                        "producer": producer,
                        "run_id": persisted_run,
                        "artifact_id": artifact_id,
                        "duration_ms": duration_ms,
                        "input_artifact_ids": input_artifact_ids,
                        "input_run_ids": input_run_ids,
                        "result": result,
                    }
                )
                _extract_metrics(operation, result, item["metrics"])
                item_succeeded += 1
                succeeded_stages += 1
            except Exception as exc:  # batch boundaries intentionally retain per-item errors
                duration_ms = max(0, round((time.perf_counter() - tick) * 1000))
                item["stages"].append(
                    {
                        "operation": operation,
                        "status": "failed",
                        "duration_ms": duration_ms,
                        "input_artifact_ids": input_artifact_ids,
                        "input_run_ids": input_run_ids,
                        "error": {"code": "execution_error", "message": str(exc)},
                    }
                )
                item_failed += 1
                failed_stages += 1
                if fail_fast:
                    break
        item["status"] = _status(item_succeeded, item_failed)
        items.append(item)

    market_stage = None
    if "market" in operations and not (fail_fast and failed_stages):
        stage_started = _now()
        tick = time.perf_counter()
        try:
            result, producer = execute_multiple(
                "market",
                products,
                {**parameters.get("market", {}), "seed": seed},
                f"{batch_id}-market",
            )
            result = jsonable(result)
            duration_ms = max(0, round((time.perf_counter() - tick) * 1000))
            run_id, artifact_id = _persist_stage(
                workspace,
                batch_id=batch_id,
                product_id=product_ids[0],
                operation="market",
                result=result,
                producer=producer,
                started_at=stage_started,
                duration_ms=duration_ms,
                input_artifact_ids=input_artifact_ids,
                input_run_ids=input_run_ids,
            )
            market_stage = {
                "operation": "market",
                "status": "succeeded",
                "producer": producer,
                "run_id": run_id,
                "artifact_id": artifact_id,
                "duration_ms": duration_ms,
                "input_artifact_ids": input_artifact_ids,
                "input_run_ids": input_run_ids,
                "result": result,
            }
            succeeded_stages += 1
        except Exception as exc:
            market_stage = {
                "operation": "market",
                "status": "failed",
                "duration_ms": max(0, round((time.perf_counter() - tick) * 1000)),
                "input_artifact_ids": input_artifact_ids,
                "input_run_ids": input_run_ids,
                "error": {"code": "execution_error", "message": str(exc)},
            }
            failed_stages += 1

    prices = [item["metrics"].get("price") for item in items]
    values = [item["metrics"].get("value") for item in items]
    batch = {
        "batch_id": batch_id,
        "label": label.strip() or "Untitled batch",
        "scenario_id": scenario_id,
        "status": _status(succeeded_stages, failed_stages),
        "seed": seed,
        "fail_fast": fail_fast,
        "input_artifact_ids": input_artifact_ids,
        "input_run_ids": input_run_ids,
        "operations": operations,
        "product_ids": product_ids,
        "started_at": started_at,
        "finished_at": _now(),
        "summary": {
            "products": len(items),
            "succeeded_items": sum(item["status"] == "succeeded" for item in items),
            "partial_items": sum(item["status"] == "partial" for item in items),
            "failed_items": sum(item["status"] == "failed" for item in items),
            "succeeded_stages": succeeded_stages,
            "failed_stages": failed_stages,
            "total_value": round(sum(value for value in values if value is not None), 2),
            "total_price": round(sum(price for price in prices if price is not None), 2),
        },
        "items": items,
        "market_stage": market_stage,
    }
    workspace.put("batches", batch_id, batch)
    return batch


__all__ = ["execute_batch"]
