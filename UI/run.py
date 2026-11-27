"""Start the local DataValor workbench."""

from __future__ import annotations

import argparse
import os

try:
    from .paths import prepare_import_paths
except ImportError:  # Supports direct execution as ``python UI/run.py``.
    from paths import prepare_import_paths


def main() -> None:
    repository_root, _ = prepare_import_paths()
    parser = argparse.ArgumentParser(description="Run the DataValor local workbench")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8080, type=int)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--auth", action="store_true", help="enable account login and isolated workspaces")
    parser.add_argument("--workspace-root", help="base directory for account workspaces")
    parser.add_argument("--auth-root", help="private directory for account records and session key")
    parser.add_argument("--secure-cookie", action="store_true", help="mark the login cookie HTTPS-only")
    args = parser.parse_args()
    if args.auth:
        os.environ["DATAVALOR_AUTH_ENABLED"] = "1"
    if args.workspace_root:
        os.environ["DATAVALOR_WORKSPACE_ROOT"] = args.workspace_root
    if args.auth_root:
        os.environ["DATAVALOR_AUTH_ROOT"] = args.auth_root
    if args.secure_cookie:
        os.environ["DATAVALOR_SESSION_SECURE"] = "1"
    import uvicorn

    options = {
        "host": args.host,
        "port": args.port,
        "reload": args.reload,
        "app_dir": str(repository_root),
    }
    if args.reload:
        options["reload_dirs"] = [str(repository_root / "UI"), str(repository_root / "src")]
    uvicorn.run("UI.server.app:app", **options)


if __name__ == "__main__":
    main()
