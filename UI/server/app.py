from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from datavalor.toolkit.capabilities import probe_external_capabilities

from ..services.components import component_catalog
from ..services.operations import execute, jsonable
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
    product_id: str
    parameters: dict[str, Any] = Field(default_factory=dict)


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
        product = workspace.get("products", payload.product_id)
        if product is None:
            raise HTTPException(404, "product not found")
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        started = datetime.now(timezone.utc)
        try:
            result, producer = execute(operation, product, payload.parameters, run_id)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        artifact_id = f"artifact-{uuid.uuid4().hex[:12]}"
        artifact = {"artifact_id": artifact_id, "kind": operation, "producer": producer, "payload": result, "created_at": datetime.now(timezone.utc).isoformat()}
        run = {"run_id": run_id, "operation": operation, "product_id": payload.product_id, "status": "succeeded", "artifact_id": artifact_id, "started_at": started.isoformat(), "finished_at": datetime.now(timezone.utc).isoformat()}
        workspace.put("artifacts", artifact_id, artifact)
        workspace.put("runs", run_id, run)
        return envelope({"run_id": run_id, "artifact_id": artifact_id, "result": result})

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
        return envelope({"summary": {"products": len(workspace.list("products")), "runs": len(workspace.list("runs")), "artifacts": len(workspace.list("artifacts")), "components": len(components_data), "available_capabilities": sum(bool(item["available"]) for item in capabilities_data)}, "recent_runs": list(reversed(workspace.list("runs")))[:5], "modules": sorted({item["module"] for item in components_data})})

    app.mount("/", StaticFiles(directory=ui_root, html=True), name="ui")

    return app


app = create_app()
