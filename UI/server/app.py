from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from datavalor.toolkit.capabilities import probe_external_capabilities

from ..services.batches import execute_batch
from ..services.components import component_catalog
from ..services.input_parsing import parse_input
from ..services.market_workbench import market_schema
from ..services.operations import execute_multiple, jsonable
from ..services.pricing_workbench import pricing_schema
from ..services.scenarios import load_scenario, scenario_catalog
from ..services.workspace import Workspace


class ProductPayload(BaseModel):
    product_id: str
    title: str = ""
    owner_id: str = "local-owner"
    version: str = "1"
    description: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    rights: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    records: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("product_id")
    @classmethod
    def safe_id(cls, value: str) -> str:
        return Workspace.validate_id(value)


class OperationPayload(BaseModel):
    product_id: str | None = None
    product_ids: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("product_id")
    @classmethod
    def safe_optional_id(cls, value: str | None) -> str | None:
        return Workspace.validate_id(value) if value is not None else None

    @field_validator("product_ids")
    @classmethod
    def safe_product_ids(cls, values: list[str]) -> list[str]:
        return [Workspace.validate_id(value) for value in values]


class InputPreviewPayload(BaseModel):
    input_type: str
    content: Any
    options: dict[str, Any] = Field(default_factory=dict)


class BatchPayload(BaseModel):
    product_ids: list[str]
    operations: list[str]
    parameters: dict[str, dict[str, Any]] = Field(default_factory=dict)
    label: str = "Untitled batch"
    scenario_id: str | None = None
    seed: int = 0
    fail_fast: bool = False

    @field_validator("product_ids")
    @classmethod
    def safe_batch_product_ids(cls, values: list[str]) -> list[str]:
        return [Workspace.validate_id(value) for value in values]

    @field_validator("scenario_id")
    @classmethod
    def safe_scenario_id(cls, value: str | None) -> str | None:
        return Workspace.validate_id(value) if value is not None else None


def envelope(data: Any, warnings: list[str] | None = None) -> dict[str, Any]:
    return {"ok": True, "data": data, "warnings": warnings or [], "meta": {"request_id": str(uuid.uuid4())}}


def create_app(workspace_root: str | Path | None = None) -> FastAPI:
    ui_root = Path(__file__).resolve().parents[1]
    workspace = Workspace(workspace_root or ui_root / "workspace")
    app = FastAPI(title="DataValor Local Workbench", version="0.1.0")

    @app.get("/api/health")
    def health():
        return envelope({"status": "ready", "workspace": str(workspace.root)})

    @app.get("/api/components")
    def components():
        return envelope({"components": component_catalog()})

    @app.post("/api/inputs/preview")
    def preview_input(payload: InputPreviewPayload):
        options = dict(payload.options)
        if payload.input_type == "catalog":
            options["available_references"] = [item["product_id"] for item in workspace.list("products")]
        elif payload.input_type == "artifact":
            options["available_references"] = [item["artifact_id"] for item in workspace.list("artifacts")]
        return envelope({"preview": jsonable(parse_input(payload.input_type, payload.content, options))})

    @app.get("/api/workbench/schemas")
    def workbench_schemas():
        return envelope({"pricing": pricing_schema(), "market": market_schema()})

    @app.get("/api/workbench/scenarios")
    def workbench_scenarios():
        return envelope({"scenarios": scenario_catalog()})

    @app.post("/api/workbench/scenarios/{scenario_id}/load")
    def load_workbench_scenario(scenario_id: str):
        try:
            Workspace.validate_id(scenario_id)
            return envelope(load_scenario(workspace, scenario_id))
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/api/capabilities")
    def capabilities():
        return envelope({"capabilities": [jsonable(item) for item in probe_external_capabilities()]})

    @app.get("/api/products")
    def list_products():
        return envelope({"products": workspace.list("products")})

    @app.post("/api/products", status_code=201)
    def create_product(payload: ProductPayload):
        if workspace.get("products", payload.product_id) is not None:
            raise HTTPException(409, "product already exists")
        value = payload.model_dump()
        workspace.put("products", payload.product_id, value)
        return envelope({"product": value})

    @app.get("/api/products/{product_id}")
    def get_product(product_id: str):
        try:
            value = workspace.get("products", product_id)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if value is None:
            raise HTTPException(404, "product not found")
        return envelope({"product": value})

    @app.put("/api/products/{product_id}")
    def update_product(product_id: str, payload: ProductPayload):
        if product_id != payload.product_id:
            raise HTTPException(422, "path and payload product id must match")
        value = payload.model_dump()
        workspace.put("products", product_id, value)
        return envelope({"product": value})

    @app.delete("/api/products/{product_id}")
    def delete_product(product_id: str):
        return envelope({"deleted": workspace.delete("products", product_id)})

    @app.post("/api/operations/{operation}")
    def run_operation(operation: str, payload: OperationPayload):
        product_ids = payload.product_ids or ([payload.product_id] if payload.product_id else [])
        if not product_ids:
            raise HTTPException(422, "product_id or product_ids is required")
        products = [workspace.get("products", product_id) for product_id in product_ids]
        missing = [product_id for product_id, product in zip(product_ids, products) if product is None]
        if missing:
            raise HTTPException(404, f"products not found: {', '.join(missing)}")
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        started = datetime.now(timezone.utc)
        try:
            result, producer = execute_multiple(operation, products, payload.parameters, run_id)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        artifact_id = f"artifact-{uuid.uuid4().hex[:12]}"
        artifact = {"artifact_id": artifact_id, "kind": operation, "producer": producer, "payload": result, "created_at": datetime.now(timezone.utc).isoformat()}
        run = {"run_id": run_id, "operation": operation, "product_id": product_ids[0], "product_ids": product_ids, "status": "succeeded", "artifact_id": artifact_id, "started_at": started.isoformat(), "finished_at": datetime.now(timezone.utc).isoformat()}
        workspace.put("artifacts", artifact_id, artifact)
        workspace.put("runs", run_id, run)
        return envelope({"run_id": run_id, "artifact_id": artifact_id, "result": result})

    @app.post("/api/batches", status_code=201)
    def run_batch(payload: BatchPayload):
        try:
            batch = execute_batch(
                workspace,
                product_ids=payload.product_ids,
                operations=payload.operations,
                parameters=payload.parameters,
                label=payload.label,
                scenario_id=payload.scenario_id,
                seed=payload.seed,
                fail_fast=payload.fail_fast,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return envelope({"batch": batch})

    @app.get("/api/batches")
    def list_batches():
        return envelope({"batches": list(reversed(workspace.list("batches")))})

    @app.get("/api/batches/{batch_id}")
    def get_batch(batch_id: str):
        try:
            value = workspace.get("batches", batch_id)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if value is None:
            raise HTTPException(404, "batch not found")
        return envelope({"batch": value})

    @app.get("/api/runs")
    def list_runs():
        return envelope({"runs": list(reversed(workspace.list("runs")))})

    @app.get("/api/artifacts")
    def list_artifacts():
        return envelope({"artifacts": list(reversed(workspace.list("artifacts")))})

    @app.get("/api/artifacts/{artifact_id}")
    def get_artifact(artifact_id: str):
        value = workspace.get("artifacts", artifact_id)
        if value is None:
            raise HTTPException(404, "artifact not found")
        return envelope({"artifact": value})

    @app.get("/api/dashboard")
    def dashboard():
        components_data = component_catalog()
        capabilities_data = [jsonable(item) for item in probe_external_capabilities()]
        return envelope({"summary": {"products": len(workspace.list("products")), "batches": len(workspace.list("batches")), "runs": len(workspace.list("runs")), "artifacts": len(workspace.list("artifacts")), "components": len(components_data), "available_capabilities": sum(bool(item["available"]) for item in capabilities_data)}, "recent_runs": list(reversed(workspace.list("runs")))[:5], "modules": sorted({item["module"] for item in components_data})})

    app.mount("/", StaticFiles(directory=ui_root, html=True), name="ui")

    return app


app = create_app()
