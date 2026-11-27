from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from datavalor.toolkit.capabilities import probe_external_capabilities

from ..services.batches import execute_batch
from ..services.components import component_catalog
from ..services.evaluation_workbench import evaluation_schema
from ..services.input_parsing import parse_input
from ..services.market_agents import generate_agent_orders
from ..services.market_workbench import market_schema
from ..services.operations import execute_multiple, jsonable
from ..services.pricing_workbench import pricing_schema
from ..services.scenarios import load_scenario, scenario_catalog
from ..services.valuation_workbench import valuation_schema
from ..services.workspace import Workspace
from .auth import (
    Account,
    AccountStore,
    AccountWorkspace,
    AuthenticationMiddleware,
    LoginThrottle,
    SessionSigner,
    current_account,
    load_or_create_session_secret,
)


class LoginPayload(BaseModel):
    username: str
    password: str


class AccountCreatePayload(BaseModel):
    username: str
    password: str
    role: str = "user"


class AccountActivePayload(BaseModel):
    active: bool


class PasswordResetPayload(BaseModel):
    password: str


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


class ParticipantPayload(BaseModel):
    participant_id: str
    name: str = ""
    role: str
    budget: float = Field(default=0, ge=0)
    currency: str = "CNY"
    reputation: float = Field(default=0.9, ge=0, le=1)
    description: str = ""
    product_ids: list[str] = Field(default_factory=list)
    scenario_ids: list[str] = Field(default_factory=list)
    delegation_mode: str = "self_managed"
    strategy: str = "manual"
    strategy_parameters: dict[str, Any] = Field(default_factory=dict)
    agent_config: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("participant_id")
    @classmethod
    def safe_id(cls, value: str) -> str:
        return Workspace.validate_id(value)

    @field_validator("role")
    @classmethod
    def known_role(cls, value: str) -> str:
        if value not in {"buyer", "seller", "intermediary", "operator"}:
            raise ValueError("role must be buyer, seller, intermediary, or operator")
        return value

    @field_validator("delegation_mode")
    @classmethod
    def known_delegation_mode(cls, value: str) -> str:
        if value not in {"self_managed", "platform_managed"}:
            raise ValueError("delegation_mode must be self_managed or platform_managed")
        return value

    @field_validator("agent_config")
    @classmethod
    def valid_agent_config(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            return value
        rationality = float(value.get("rationality", 1.0))
        if not 0 <= rationality <= 1:
            raise ValueError("agent_config rationality must be between 0 and 1")
        style = str(value.get("style", "balanced"))
        if style not in {"conservative", "balanced", "aggressive", "exploratory"}:
            raise ValueError("agent_config style is not supported")
        model = str(value.get("model", "utility_maximizer"))
        if model not in {"utility_maximizer", "budget_pacing", "bundle_optimizer", "reserve_optimizer"}:
            raise ValueError("agent_config model is not supported")
        preferences = value.get("preferences", {})
        if not isinstance(preferences, dict) or any(float(weight) < 0 for weight in preferences.values()):
            raise ValueError("agent_config preferences must be non-negative numeric weights")
        return {
            **value,
            "enabled": bool(value.get("enabled", False)),
            "rationality": rationality,
            "style": style,
            "model": model,
            "preferred_mechanisms": [str(item) for item in value.get("preferred_mechanisms", ())],
            "preferences": {str(name): float(weight) for name, weight in preferences.items()},
        }

    @field_validator("product_ids", "scenario_ids")
    @classmethod
    def safe_references(cls, values: list[str]) -> list[str]:
        return [Workspace.validate_id(value) for value in values]


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
    input_artifact_ids: list[str] = Field(default_factory=list)
    include_related_content: bool = True

    @field_validator("product_ids")
    @classmethod
    def safe_batch_product_ids(cls, values: list[str]) -> list[str]:
        return [Workspace.validate_id(value) for value in values]

    @field_validator("scenario_id")
    @classmethod
    def safe_scenario_id(cls, value: str | None) -> str | None:
        return Workspace.validate_id(value) if value is not None else None

    @field_validator("input_artifact_ids")
    @classmethod
    def safe_artifact_ids(cls, values: list[str]) -> list[str]:
        return [Workspace.validate_id(value) for value in values]


class AgentOrderPayload(BaseModel):
    participant_ids: list[str]
    product_ids: list[str]
    mechanism: str

    @field_validator("participant_ids", "product_ids")
    @classmethod
    def safe_ids(cls, values: list[str]) -> list[str]:
        return [Workspace.validate_id(value) for value in values]


def envelope(data: Any, warnings: list[str] | None = None) -> dict[str, Any]:
    return {"ok": True, "data": data, "warnings": warnings or [], "meta": {"request_id": str(uuid.uuid4())}}


def create_app(
    workspace_root: str | Path | None = None,
    *,
    auth_enabled: bool = False,
    auth_root: str | Path | None = None,
    admin_username: str | None = None,
    admin_password: str | None = None,
    session_secret: bytes | None = None,
    session_secure: bool = False,
) -> FastAPI:
    ui_root = Path(__file__).resolve().parents[1]
    workspace_path = Path(workspace_root or ui_root / "workspace")
    workspace: Workspace | AccountWorkspace
    account_store: AccountStore | None = None
    session_signer: SessionSigner | None = None
    if auth_enabled:
        private_root = Path(auth_root or (Path.home() / ".datavalor" / "auth"))
        static_root = ui_root.resolve()
        for label, candidate in (
            ("workspace root", workspace_path),
            ("authentication root", private_root),
        ):
            try:
                candidate.resolve().relative_to(static_root)
            except ValueError:
                continue
            raise ValueError(f"{label} must be outside the UI static directory")
        account_store = AccountStore(private_root)
        if not account_store.list_accounts():
            if not admin_username or not admin_password:
                raise RuntimeError(
                    "admin username and password are required when enabling a new account store"
                )
            account_store.bootstrap_admin(admin_username, admin_password)
        session_signer = SessionSigner(
            session_secret or load_or_create_session_secret(private_root)
        )
        workspace = AccountWorkspace(workspace_path)
    else:
        workspace = Workspace(workspace_path)
    app = FastAPI(title="DataValor Local Workbench", version="0.1.0")
    app.state.auth_enabled = auth_enabled
    app.state.account_store = account_store
    app.state.workspace = workspace
    login_throttle = LoginThrottle()
    app.state.login_throttle = login_throttle

    def account_payload(account: Account) -> dict[str, Any]:
        return {
            "account_id": account.account_id,
            "username": account.username,
            "role": account.role,
            "active": account.active,
            "session_version": account.session_version,
            "created_at": account.created_at,
        }

    def signed_in_account() -> Account:
        account = current_account()
        if account is None:
            raise HTTPException(401, "authentication required")
        return account

    def administrator() -> Account:
        account = signed_in_account()
        if account.role != "admin":
            raise HTTPException(403, "administrator access required")
        return account

    @app.get("/login", include_in_schema=False)
    def login_page():
        return FileResponse(ui_root / "login.html")

    @app.get("/admin", include_in_schema=False)
    def admin_page():
        administrator()
        return FileResponse(ui_root / "admin.html")

    @app.post("/api/auth/login")
    def login(payload: LoginPayload, request: Request, response: Response):
        if account_store is None or session_signer is None:
            raise HTTPException(404, "authentication is not enabled")
        source = request.client.host if request.client else "unknown"
        username = payload.username.strip().lower()
        if not login_throttle.allowed(source, username):
            raise HTTPException(429, "too many login attempts; try again later")
        account = account_store.authenticate(payload.username, payload.password)
        if account is None:
            login_throttle.record_failure(source, username)
            raise HTTPException(401, "invalid username or password")
        login_throttle.record_success(username)
        response.set_cookie(
            "datavalor_session",
            session_signer.issue(account),
            httponly=True,
            secure=session_secure,
            samesite="lax",
            max_age=session_signer.ttl_seconds,
            path="/",
        )
        return envelope({"account": account_payload(account)})

    @app.post("/api/auth/logout")
    def logout(response: Response):
        response.delete_cookie("datavalor_session", path="/", samesite="lax")
        return envelope({"logged_out": True})

    @app.get("/api/auth/me")
    def auth_me():
        return envelope({"account": account_payload(signed_in_account())})

    @app.get("/api/admin/accounts")
    def list_accounts():
        administrator()
        assert account_store is not None
        return envelope({"accounts": [account_payload(item) for item in account_store.list_accounts()]})

    @app.post("/api/admin/accounts", status_code=201)
    def create_account(payload: AccountCreatePayload):
        administrator()
        assert account_store is not None
        try:
            account = account_store.create_account(payload.username, payload.password, payload.role)
        except ValueError as exc:
            status = 409 if "already exists" in str(exc) else 422
            raise HTTPException(status, str(exc)) from exc
        return envelope({"account": account_payload(account)})

    @app.patch("/api/admin/accounts/{account_id}")
    def update_account(account_id: str, payload: AccountActivePayload):
        administrator()
        assert account_store is not None
        try:
            account = account_store.set_active(account_id, payload.active)
        except ValueError as exc:
            status = 404 if "not found" in str(exc) else 422
            raise HTTPException(status, str(exc)) from exc
        return envelope({"account": account_payload(account)})

    @app.post("/api/admin/accounts/{account_id}/password")
    def reset_account_password(account_id: str, payload: PasswordResetPayload):
        administrator()
        assert account_store is not None
        try:
            account = account_store.reset_password(account_id, payload.password)
        except ValueError as exc:
            status = 404 if "not found" in str(exc) else 422
            raise HTTPException(status, str(exc)) from exc
        return envelope({"account": account_payload(account)})

    @app.get("/api/health")
    def health():
        data = {"status": "ready", "authentication": "enabled" if auth_enabled else "disabled"}
        if not auth_enabled:
            data["workspace"] = str(workspace.root)
        return envelope(data)

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
        return envelope({
            "evaluation": evaluation_schema(),
            "valuation": valuation_schema(),
            "pricing": pricing_schema(),
            "market": market_schema(),
        })

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

    @app.get("/api/participants")
    def list_participants():
        return envelope({"participants": workspace.list("participants")})

    @app.post("/api/participants", status_code=201)
    def create_participant(payload: ParticipantPayload):
        value = payload.model_dump()
        if workspace.get("participants", payload.participant_id) is not None:
            raise HTTPException(409, "participant already exists")
        workspace.put("participants", payload.participant_id, value)
        return envelope({"participant": value})

    @app.post("/api/market/agent-orders")
    def market_agent_orders(payload: AgentOrderPayload):
        known_participants = {item["participant_id"] for item in workspace.list("participants")}
        known_products = {item["product_id"] for item in workspace.list("products")}
        missing_participants = sorted(set(payload.participant_ids) - known_participants)
        missing_products = sorted(set(payload.product_ids) - known_products)
        if missing_participants:
            raise HTTPException(422, f"participants not found: {', '.join(missing_participants)}")
        if missing_products:
            raise HTTPException(422, f"products not found: {', '.join(missing_products)}")
        return envelope(generate_agent_orders(
            workspace.list("participants"), workspace.list("products"), workspace.list("artifacts"),
            participant_ids=payload.participant_ids, product_ids=payload.product_ids,
            mechanism=payload.mechanism,
        ))

    @app.put("/api/participants/{participant_id}")
    def update_participant(participant_id: str, payload: ParticipantPayload):
        Workspace.validate_id(participant_id)
        if participant_id != payload.participant_id:
            raise HTTPException(422, "path and payload participant id must match")
        value = payload.model_dump()
        workspace.put("participants", participant_id, value)
        return envelope({"participant": value})

    @app.delete("/api/participants/{participant_id}")
    def delete_participant(participant_id: str):
        return envelope({"deleted": workspace.delete("participants", participant_id)})

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
                input_artifact_ids=payload.input_artifact_ids,
                include_related_content=payload.include_related_content,
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
        products = workspace.list("products")
        participants = workspace.list("participants")
        artifacts = workspace.list("artifacts")
        batches = workspace.list("batches")
        runs = workspace.list("runs")
        artifact_counts = {
            name: sum(item.get("kind") == name for item in artifacts)
            for name in ("governance", "profile", "evaluation", "valuation", "pricing", "market")
        }

        def number(value: Any) -> float:
            try:
                return float(value)
            except (TypeError, ValueError):
                return 0.0

        total_records = sum(number(item.get("data", {}).get("record_count", len(item.get("records", ())))) for item in products)
        reference_value = sum(number(item.get("metadata", {}).get("asking_price")) for item in products)
        total_value = sum(
            number((item.get("payload", {}).get("estimates") or [{}])[0].get("value"))
            for item in artifacts if item.get("kind") == "valuation"
        )
        total_price = sum(
            number(item.get("payload", {}).get("price", {}).get("amount"))
            for item in artifacts if item.get("kind") == "pricing"
        )
        allocations = sum(
            len(item.get("payload", {}).get("outcome", {}).get("allocations", ()))
            + len((item.get("payload", {}).get("bundle_selection") or {}).get("matches", ()))
            + len(item.get("payload", {}).get("multi_attribute_matches", ()))
            for item in artifacts if item.get("kind") == "market"
        )
        module_stats = {
            "products": {"registered": len(products), "total_records": int(total_records), "reference_value": reference_value},
            "governance": {"registered": artifact_counts["governance"]},
            "profile": {"registered": artifact_counts["profile"]},
            "evaluation": {"registered": artifact_counts["evaluation"]},
            "valuation": {"registered": artifact_counts["valuation"], "total_value": total_value},
            "pricing": {"registered": artifact_counts["pricing"], "total_price": total_price},
            "market": {"registered": artifact_counts["market"], "participants": len(participants), "allocations": allocations},
        }
        return envelope({
            "summary": {
                "products": len(products), "participants": len(participants),
                "total_records": int(total_records), "reference_value": reference_value,
                "batches": len(batches), "runs": len(runs), "artifacts": len(artifacts),
                "components": len(components_data),
                "available_capabilities": sum(bool(item["available"]) for item in capabilities_data),
            },
            "recent_runs": list(reversed(runs))[:5],
            "modules": module_stats,
        })

    if auth_enabled:
        app.add_middleware(
            AuthenticationMiddleware,
            store=account_store,
            signer=session_signer,
        )

    app.mount("/", StaticFiles(directory=ui_root, html=True), name="ui")

    return app


def create_app_from_environment() -> FastAPI:
    def enabled(name: str, default: bool = False) -> bool:
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "on"}

    workspace_root = os.getenv("DATAVALOR_WORKSPACE_ROOT") or None
    auth_root = os.getenv("DATAVALOR_AUTH_ROOT") or None
    return create_app(
        workspace_root,
        auth_enabled=enabled("DATAVALOR_AUTH_ENABLED"),
        auth_root=auth_root,
        admin_username=os.getenv("DATAVALOR_ADMIN_USERNAME") or None,
        admin_password=os.getenv("DATAVALOR_ADMIN_PASSWORD") or None,
        session_secure=enabled("DATAVALOR_SESSION_SECURE"),
    )


app = create_app_from_environment()
