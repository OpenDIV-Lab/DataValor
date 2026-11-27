from __future__ import annotations

import base64
import fcntl
import hashlib
import hmac
import json
import re
import secrets
import time
import uuid
from collections import defaultdict, deque
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Iterator

from starlette.responses import JSONResponse, RedirectResponse

from ..services.workspace import Workspace

USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
PBKDF2_ITERATIONS = 310_000


def normalize_username(value: str) -> str:
    username = value.strip().lower()
    if not USERNAME.fullmatch(username):
        raise ValueError("username must be 3-64 lowercase letters, numbers, dot, dash, or underscore")
    return username


def validate_password(value: str) -> str:
    if len(value) < 10:
        raise ValueError("password must contain at least 10 characters")
    if len(value) > 512:
        raise ValueError("password must contain at most 512 characters")
    return value


def _b64_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    validate_password(password)
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${_b64_encode(salt)}${_b64_encode(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), _b64_decode(salt), int(iterations)
        )
        return hmac.compare_digest(actual, _b64_decode(expected))
    except (TypeError, ValueError):
        return False


@dataclass(frozen=True)
class Account:
    account_id: str
    username: str
    role: str
    active: bool
    session_version: int
    created_at: str


class AccountStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.root.chmod(0o700)
        self.path = self.root / "accounts.json"
        self.lock_path = self.root / "accounts.lock"
        self._lock = RLock()
        with self._locked():
            if not self.path.exists():
                self._write({"version": 1, "accounts": []})

    @contextmanager
    def _locked(self) -> Iterator[None]:
        """Serialize account reads and mutations across threads and worker processes."""
        with self._lock:
            with self.lock_path.open("a+b") as lock_file:
                self.lock_path.chmod(0o600)
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _read(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, payload: dict[str, Any]) -> None:
        temporary = self.root / f".accounts-{uuid.uuid4().hex}.tmp"
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temporary.chmod(0o600)
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _public(record: dict[str, Any]) -> Account:
        return Account(**{key: record[key] for key in Account.__dataclass_fields__})

    def list_accounts(self) -> list[Account]:
        with self._locked():
            records = self._read()["accounts"]
            return [self._public(record) for record in sorted(records, key=lambda item: item["created_at"])]

    def get(self, account_id: str) -> Account | None:
        with self._locked():
            record = next(
                (item for item in self._read()["accounts"] if item["account_id"] == account_id), None
            )
            return self._public(record) if record else None

    def get_by_username(self, username: str) -> Account | None:
        try:
            normalized = normalize_username(username)
        except ValueError:
            return None
        with self._locked():
            record = next(
                (item for item in self._read()["accounts"] if item["username"] == normalized), None
            )
            return self._public(record) if record else None

    def bootstrap_admin(self, username: str, password: str) -> Account:
        normalized = normalize_username(username)
        validate_password(password)
        with self._locked():
            payload = self._read()
            if payload["accounts"]:
                existing = next(
                    (item for item in payload["accounts"] if item["username"] == normalized), None
                )
                if existing and existing["role"] == "admin":
                    return self._public(existing)
                raise ValueError("administrator bootstrap is only allowed for an empty account store")
            return self._create_locked(payload, normalized, password, "admin")

    def create_account(self, username: str, password: str, role: str = "user") -> Account:
        normalized = normalize_username(username)
        validate_password(password)
        if role not in {"admin", "user"}:
            raise ValueError("role must be admin or user")
        with self._locked():
            payload = self._read()
            if any(item["username"] == normalized for item in payload["accounts"]):
                raise ValueError("username already exists")
            return self._create_locked(payload, normalized, password, role)

    def _create_locked(
        self, payload: dict[str, Any], username: str, password: str, role: str
    ) -> Account:
        record = {
            "account_id": f"acct-{uuid.uuid4().hex}",
            "username": username,
            "role": role,
            "active": True,
            "session_version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "password_hash": hash_password(password),
        }
        payload["accounts"].append(record)
        self._write(payload)
        return self._public(record)

    def authenticate(self, username: str, password: str) -> Account | None:
        try:
            normalized = normalize_username(username)
        except ValueError:
            normalized = "invalid-user"
        with self._locked():
            record = next(
                (item for item in self._read()["accounts"] if item["username"] == normalized), None
            )
        encoded = record["password_hash"] if record else (
            f"pbkdf2_sha256${PBKDF2_ITERATIONS}$AAAAAAAAAAAAAAAAAAAAAA$"
            "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        )
        valid = verify_password(password, encoded)
        if not record or not valid or not record["active"]:
            return None
        return self._public(record)

    def set_active(self, account_id: str, active: bool) -> Account:
        with self._locked():
            payload = self._read()
            record = next(
                (item for item in payload["accounts"] if item["account_id"] == account_id), None
            )
            if record is None:
                raise ValueError("account not found")
            if record["active"] and not active and record["role"] == "admin":
                active_admins = sum(
                    item["role"] == "admin" and item["active"] for item in payload["accounts"]
                )
                if active_admins <= 1:
                    raise ValueError("last active administrator cannot be deactivated")
            record["active"] = bool(active)
            if not active:
                record["session_version"] += 1
            self._write(payload)
            return self._public(record)

    def reset_password(self, account_id: str, password: str) -> Account:
        validate_password(password)
        with self._locked():
            payload = self._read()
            record = next(
                (item for item in payload["accounts"] if item["account_id"] == account_id), None
            )
            if record is None:
                raise ValueError("account not found")
            record["password_hash"] = hash_password(password)
            record["session_version"] += 1
            self._write(payload)
            return self._public(record)


class SessionSigner:
    def __init__(self, secret: bytes, ttl_seconds: int = 8 * 60 * 60):
        if len(secret) < 32:
            raise ValueError("session secret must contain at least 32 bytes")
        self.secret = secret
        self.ttl_seconds = ttl_seconds

    def issue(self, account: Account, *, now: int | None = None) -> str:
        issued_at = int(time.time() if now is None else now)
        payload = json.dumps(
            {
                "sub": account.account_id,
                "ver": account.session_version,
                "exp": issued_at + self.ttl_seconds,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        encoded = _b64_encode(payload)
        signature = _b64_encode(hmac.new(self.secret, encoded.encode("ascii"), hashlib.sha256).digest())
        return f"{encoded}.{signature}"

    def verify(
        self, token: str, store: AccountStore, *, now: int | None = None
    ) -> Account | None:
        try:
            encoded, signature = token.split(".", 1)
            expected = hmac.new(self.secret, encoded.encode("ascii"), hashlib.sha256).digest()
            if not hmac.compare_digest(expected, _b64_decode(signature)):
                return None
            payload = json.loads(_b64_decode(encoded))
            if int(payload["exp"]) < int(time.time() if now is None else now):
                return None
            account = store.get(str(payload["sub"]))
            if account is None or not account.active:
                return None
            if account.session_version != int(payload["ver"]):
                return None
            return account
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return None


class LoginThrottle:
    """Bound failed password work by both client address and normalized account name."""

    def __init__(
        self,
        *,
        account_limit: int = 8,
        source_limit: int = 24,
        window_seconds: int = 60,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.account_limit = account_limit
        self.source_limit = source_limit
        self.window_seconds = window_seconds
        self.clock = clock
        self._attempts: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = RLock()

    def _bucket(self, key: tuple[str, str], now: float) -> deque[float]:
        attempts = self._attempts[key]
        cutoff = now - self.window_seconds
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()
        return attempts

    def allowed(self, source: str, username: str) -> bool:
        now = self.clock()
        with self._lock:
            return (
                len(self._bucket(("source", source), now)) < self.source_limit
                and len(self._bucket(("account", username), now)) < self.account_limit
            )

    def record_failure(self, source: str, username: str) -> None:
        now = self.clock()
        with self._lock:
            self._bucket(("source", source), now).append(now)
            self._bucket(("account", username), now).append(now)

    def record_success(self, username: str) -> None:
        with self._lock:
            self._attempts.pop(("account", username), None)


_CURRENT_ACCOUNT: ContextVar[Account | None] = ContextVar(
    "datavalor_current_account", default=None
)


def current_account() -> Account | None:
    return _CURRENT_ACCOUNT.get()


class AccountWorkspace:
    """Resolve the existing Workspace API against the authenticated account."""

    def __init__(self, root: str | Path):
        self.base_root = Path(root)
        self.base_root.mkdir(parents=True, exist_ok=True)

    def _workspace(self) -> Workspace:
        account = current_account()
        if account is None:
            raise RuntimeError("authenticated account context is required")
        return Workspace(self.base_root / account.account_id)

    @property
    def root(self) -> Path:
        return self._workspace().root

    def list(self, collection: str) -> list[Any]:
        return self._workspace().list(collection)

    def get(self, collection: str, item_id: str) -> Any | None:
        return self._workspace().get(collection, item_id)

    def put(self, collection: str, item_id: str, value: Any) -> None:
        self._workspace().put(collection, item_id, value)

    def delete(self, collection: str, item_id: str) -> bool:
        return self._workspace().delete(collection, item_id)


class AuthenticationMiddleware:
    def __init__(
        self,
        app,
        *,
        store: AccountStore,
        signer: SessionSigner,
        cookie_name: str = "datavalor_session",
    ):
        self.app = app
        self.store = store
        self.signer = signer
        self.cookie_name = cookie_name

    @staticmethod
    def _public(path: str) -> bool:
        return (
            path == "/login"
            or path == "/api/health"
            or path == "/api/auth/login"
            or path == "/tour"
            or path.startswith("/tour/")
            or path in {"/auth.css", "/auth.js", "/favicon.ico"}
        )

    @staticmethod
    def _storage_path(path: str) -> bool:
        return path == "/workspace" or path.startswith("/workspace/") or path.startswith(
            "/workspaces/"
        ) or path.startswith("/.datavalor-auth/")

    def _cookie(self, scope) -> str | None:
        headers = {key.lower(): value for key, value in scope.get("headers", ())}
        raw = headers.get(b"cookie", b"").decode("latin-1")
        for part in raw.split(";"):
            name, separator, value = part.strip().partition("=")
            if separator and name == self.cookie_name:
                return value
        return None

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if any(part in {".", ".."} for part in path.split("/")):
            await JSONResponse({"detail": "not found"}, status_code=404)(scope, receive, send)
            return
        if self._storage_path(path):
            await JSONResponse({"detail": "not found"}, status_code=404)(scope, receive, send)
            return
        token = self._cookie(scope)
        account = self.signer.verify(token, self.store) if token else None
        if account is None and not self._public(path):
            if path.startswith("/api/"):
                await JSONResponse(
                    {"detail": "authentication required"}, status_code=401
                )(scope, receive, send)
            else:
                await RedirectResponse("/login", status_code=303)(scope, receive, send)
            return
        context_token = _CURRENT_ACCOUNT.set(account)
        try:
            await self.app(scope, receive, send)
        finally:
            _CURRENT_ACCOUNT.reset(context_token)


def load_or_create_session_secret(root: str | Path) -> bytes:
    path = Path(root) / "session.key"
    if path.exists():
        secret = path.read_bytes()
        if len(secret) < 32:
            raise ValueError("stored session secret must contain at least 32 bytes")
        return secret
    secret = secrets.token_bytes(48)
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(secret)
    temporary.chmod(0o600)
    temporary.replace(path)
    return secret
