from __future__ import annotations

import json
import multiprocessing
from html.parser import HTMLParser
from pathlib import Path

import pytest


def _create_accounts_concurrently(auth_root: str, prefix: str, barrier, results) -> None:
    from UI.server import auth

    auth.PBKDF2_ITERATIONS = 1_000
    store = auth.AccountStore(auth_root)
    barrier.wait()
    try:
        for index in range(5):
            store.create_account(f"{prefix}-{index}", "concurrent-password")
    except Exception as exc:  # pragma: no cover - returned to the parent for assertion
        results.put(repr(exc))
    else:
        results.put(None)


def authenticated_app(tmp_path):
    from UI.server.app import create_app

    return create_app(
        tmp_path / "workspaces",
        auth_enabled=True,
        auth_root=tmp_path / "auth",
        admin_username="admin",
        admin_password="administrator-password",
        session_secret=b"c" * 32,
    )


def login(client, username: str, password: str):
    return client.post("/api/auth/login", json={"username": username, "password": password})


class ElementCatalog(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements: dict[str, tuple[str, dict[str, str | None]]] = {}

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if values.get("id"):
            self.elements[str(values["id"])] = (tag, values)


def page_elements(path: Path) -> dict[str, tuple[str, dict[str, str | None]]]:
    parser = ElementCatalog()
    parser.feed(path.read_text(encoding="utf-8"))
    return parser.elements


def test_account_store_bootstraps_admin_and_never_persists_plaintext_password(tmp_path):
    from UI.server.auth import AccountStore

    store = AccountStore(tmp_path / "auth")
    admin = store.bootstrap_admin("Platform.Admin", "correct horse battery staple")

    assert admin.username == "platform.admin"
    assert admin.role == "admin"
    assert admin.active is True
    assert store.authenticate("PLATFORM.ADMIN", "correct horse battery staple") == admin
    assert store.authenticate("platform.admin", "wrong password") is None
    raw = (tmp_path / "auth" / "accounts.json").read_text(encoding="utf-8")
    assert "correct horse battery staple" not in raw
    assert (tmp_path / "auth").stat().st_mode & 0o077 == 0
    assert (tmp_path / "auth" / "accounts.json").stat().st_mode & 0o077 == 0
    persisted = json.loads(raw)
    assert persisted["accounts"][0]["password_hash"].startswith("pbkdf2_sha256$")


def test_account_store_validates_new_accounts_and_rejects_duplicates(tmp_path):
    from UI.server.auth import AccountStore

    store = AccountStore(tmp_path / "auth")
    store.bootstrap_admin("admin", "administrator-password")
    analyst = store.create_account("Analyst-01", "analyst-password")

    assert analyst.username == "analyst-01"
    assert analyst.role == "user"
    assert store.authenticate("analyst-01", "analyst-password") == analyst
    with pytest.raises(ValueError, match="already exists"):
        store.create_account("ANALYST-01", "another-password")
    with pytest.raises(ValueError, match="username"):
        store.create_account("../escape", "another-password")
    with pytest.raises(ValueError, match="at least 10"):
        store.create_account("short-pass", "tiny")


def test_activation_and_password_reset_invalidate_access_and_old_sessions(tmp_path):
    from UI.server.auth import AccountStore, SessionSigner

    store = AccountStore(tmp_path / "auth")
    store.bootstrap_admin("admin", "administrator-password")
    analyst = store.create_account("analyst", "analyst-password")
    signer = SessionSigner(b"a" * 32, ttl_seconds=3600)
    old_token = signer.issue(analyst, now=1000)

    inactive = store.set_active(analyst.account_id, False)
    assert inactive.active is False
    assert store.authenticate("analyst", "analyst-password") is None
    assert signer.verify(old_token, store, now=1001) is None

    store.set_active(analyst.account_id, True)
    reset = store.reset_password(analyst.account_id, "replacement-password")
    assert reset.session_version == analyst.session_version + 2
    assert store.authenticate("analyst", "analyst-password") is None
    assert store.authenticate("analyst", "replacement-password") == reset
    assert signer.verify(old_token, store, now=1001) is None


def test_last_active_administrator_cannot_be_deactivated(tmp_path):
    from UI.server.auth import AccountStore

    store = AccountStore(tmp_path / "auth")
    admin = store.bootstrap_admin("admin", "administrator-password")

    with pytest.raises(ValueError, match="last active administrator"):
        store.set_active(admin.account_id, False)


def test_account_store_serializes_writes_across_processes(tmp_path):
    from UI.server import auth

    auth.PBKDF2_ITERATIONS = 1_000
    root = tmp_path / "auth"
    auth.AccountStore(root).bootstrap_admin("admin", "administrator-password")
    context = multiprocessing.get_context("fork")
    barrier = context.Barrier(2)
    results = context.Queue()
    processes = [
        context.Process(
            target=_create_accounts_concurrently,
            args=(str(root), prefix, barrier, results),
        )
        for prefix in ("team-a", "team-b")
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=10)

    assert [process.exitcode for process in processes] == [0, 0]
    assert [results.get(timeout=1), results.get(timeout=1)] == [None, None]
    assert len(auth.AccountStore(root).list_accounts()) == 11


def test_signed_session_rejects_tampering_expiry_and_unknown_account(tmp_path):
    from UI.server.auth import AccountStore, SessionSigner

    store = AccountStore(tmp_path / "auth")
    admin = store.bootstrap_admin("admin", "administrator-password")
    signer = SessionSigner(b"b" * 32, ttl_seconds=60)
    token = signer.issue(admin, now=2000)

    assert signer.verify(token, store, now=2059) == admin
    assert signer.verify(token + "x", store, now=2059) is None
    assert signer.verify(token, store, now=2061) is None
    assert signer.verify("not-a-token", store, now=2001) is None


def test_authenticated_app_keeps_tour_public_and_protects_workbench_and_api(tmp_path):
    from fastapi.testclient import TestClient

    client = TestClient(authenticated_app(tmp_path))

    assert client.get("/api/health").status_code == 200
    assert client.get("/tour/").status_code == 200
    root = client.get("/", follow_redirects=False)
    assert root.status_code == 303
    assert root.headers["location"] == "/login"
    denied = client.get("/api/products")
    assert denied.status_code == 401
    assert denied.json()["detail"] == "authentication required"
    assert client.get("/workspace/products/secret.json").status_code == 404


def test_encoded_dot_segments_cannot_escape_public_tour(tmp_path):
    from fastapi.testclient import TestClient

    client = TestClient(authenticated_app(tmp_path))

    escaped = client.get("/tour/%2e%2e/server/auth.py", follow_redirects=False)
    assert escaped.status_code == 404
    escaped_workspace = client.get(
        "/tour/%2e%2e/workspace/products/secret.json", follow_redirects=False
    )
    assert escaped_workspace.status_code == 404


def test_login_me_logout_and_generic_login_failure(tmp_path):
    from fastapi.testclient import TestClient

    client = TestClient(authenticated_app(tmp_path))

    wrong = login(client, "admin", "not-the-password")
    assert wrong.status_code == 401
    assert wrong.json()["detail"] == "invalid username or password"
    response = login(client, "admin", "administrator-password")
    assert response.status_code == 200
    assert "datavalor_session=" in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]
    me = client.get("/api/auth/me").json()["data"]["account"]
    assert me["username"] == "admin"
    assert me["role"] == "admin"
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_login_failures_are_rate_limited(tmp_path):
    from fastapi.testclient import TestClient

    client = TestClient(authenticated_app(tmp_path))

    for _ in range(8):
        assert login(client, "admin", "not-the-password").status_code == 401
    limited = login(client, "admin", "not-the-password")
    assert limited.status_code == 429
    assert limited.json()["detail"] == "too many login attempts; try again later"


def test_admin_creates_accounts_and_users_cannot_manage_accounts(tmp_path):
    from fastapi.testclient import TestClient

    app = authenticated_app(tmp_path)
    admin = TestClient(app)
    assert login(admin, "admin", "administrator-password").status_code == 200
    created = admin.post(
        "/api/admin/accounts",
        json={"username": "analyst", "password": "analyst-password", "role": "user"},
    )
    assert created.status_code == 201
    account = created.json()["data"]["account"]
    assert account["username"] == "analyst"
    assert "password" not in account and "password_hash" not in account
    assert len(admin.get("/api/admin/accounts").json()["data"]["accounts"]) == 2

    analyst = TestClient(app)
    assert login(analyst, "analyst", "analyst-password").status_code == 200
    assert analyst.get("/api/admin/accounts").status_code == 403
    assert analyst.post(
        "/api/admin/accounts",
        json={"username": "intruder", "password": "intruder-password"},
    ).status_code == 403


def test_account_workspaces_are_isolated_for_reads_and_writes(tmp_path):
    from fastapi.testclient import TestClient

    app = authenticated_app(tmp_path)
    admin = TestClient(app)
    login(admin, "admin", "administrator-password")
    admin.post(
        "/api/admin/accounts",
        json={"username": "analyst", "password": "analyst-password", "role": "user"},
    )
    analyst = TestClient(app)
    login(analyst, "analyst", "analyst-password")

    product = {
        "product_id": "private-product",
        "title": "Admin private product",
        "owner_id": "admin",
        "records": [{"value": 1}],
    }
    assert admin.post("/api/products", json=product).status_code == 201
    assert [item["title"] for item in admin.get("/api/products").json()["data"]["products"]] == [
        "Admin private product"
    ]
    assert analyst.get("/api/products").json()["data"]["products"] == []

    product["title"] = "Analyst private product"
    product["owner_id"] = "analyst"
    assert analyst.post("/api/products", json=product).status_code == 201
    assert analyst.get("/api/products").json()["data"]["products"][0]["title"] == (
        "Analyst private product"
    )
    assert admin.get("/api/products").json()["data"]["products"][0]["title"] == (
        "Admin private product"
    )
    workspace_dirs = [path for path in (tmp_path / "workspaces").iterdir() if path.is_dir()]
    assert len(workspace_dirs) == 2


def test_deactivated_account_loses_access_with_existing_cookie(tmp_path):
    from fastapi.testclient import TestClient

    app = authenticated_app(tmp_path)
    admin = TestClient(app)
    login(admin, "admin", "administrator-password")
    account = admin.post(
        "/api/admin/accounts",
        json={"username": "analyst", "password": "analyst-password"},
    ).json()["data"]["account"]
    analyst = TestClient(app)
    login(analyst, "analyst", "analyst-password")
    assert analyst.get("/api/products").status_code == 200

    disabled = admin.patch(
        f"/api/admin/accounts/{account['account_id']}", json={"active": False}
    )
    assert disabled.status_code == 200
    assert analyst.get("/api/products").status_code == 401


def test_login_and_admin_pages_expose_complete_account_workflows():
    root = Path(__file__).parents[1] / "UI"
    login_elements = page_elements(root / "login.html")
    admin_elements = page_elements(root / "admin.html")

    assert login_elements["loginForm"][0] == "form"
    assert login_elements["loginUsername"][1]["autocomplete"] == "username"
    assert login_elements["loginPassword"][1]["type"] == "password"
    assert login_elements["loginPassword"][1]["autocomplete"] == "current-password"
    assert {"accountForm", "accountUsername", "accountPassword", "accountRole"} <= admin_elements.keys()
    assert {
        "accountRows",
        "accountFeedback",
        "backToWorkbench",
        "adminLogout",
        "passwordDialog",
        "resetPasswordForm",
        "resetPassword",
        "cancelPasswordReset",
    } <= admin_elements.keys()
    assert admin_elements["resetPassword"][1]["type"] == "password"
    assert admin_elements["resetPassword"][1]["autocomplete"] == "new-password"


def test_workbench_exposes_current_account_admin_navigation_and_logout():
    root = Path(__file__).parents[1] / "UI"
    elements = page_elements(root / "index.html")

    assert {"accountIdentity", "adminAccounts", "logoutAccount"} <= elements.keys()
    assert elements["adminAccounts"][0] == "a"
    assert elements["adminAccounts"][1]["href"] == "/admin"
    assert elements["logoutAccount"][0] == "button"


def test_environment_configuration_builds_authenticated_app_with_private_roots(tmp_path, monkeypatch):
    from UI.server.app import create_app_from_environment

    monkeypatch.setenv("DATAVALOR_AUTH_ENABLED", "1")
    monkeypatch.setenv("DATAVALOR_WORKSPACE_ROOT", str(tmp_path / "workspaces"))
    monkeypatch.setenv("DATAVALOR_AUTH_ROOT", str(tmp_path / "private-auth"))
    monkeypatch.setenv("DATAVALOR_ADMIN_USERNAME", "root-admin")
    monkeypatch.setenv("DATAVALOR_ADMIN_PASSWORD", "administrator-password")
    monkeypatch.setenv("DATAVALOR_SESSION_SECURE", "1")

    app = create_app_from_environment()

    assert app.state.auth_enabled is True
    assert app.state.workspace.base_root == tmp_path / "workspaces"
    assert app.state.account_store.root == tmp_path / "private-auth"
    assert app.state.account_store.authenticate("root-admin", "administrator-password").role == "admin"


def test_authenticated_app_rejects_private_roots_inside_static_ui(tmp_path, monkeypatch):
    from UI.server import app as app_module

    fake_app_file = tmp_path / "UI" / "server" / "app.py"
    fake_app_file.parent.mkdir(parents=True)
    monkeypatch.setattr(app_module, "__file__", str(fake_app_file))

    with pytest.raises(ValueError, match="outside the UI static directory"):
        app_module.create_app(
            tmp_path / "UI" / "workspaces",
            auth_enabled=True,
            auth_root=tmp_path / "private-auth",
            admin_username="admin",
            admin_password="administrator-password",
        )
    with pytest.raises(ValueError, match="outside the UI static directory"):
        app_module.create_app(
            tmp_path / "private-workspaces",
            auth_enabled=True,
            auth_root=tmp_path / "UI" / "auth-secrets",
            admin_username="admin",
            admin_password="administrator-password",
        )
