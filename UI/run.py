"""Start the local DataValor workbench."""

from __future__ import annotations

import argparse

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
    args = parser.parse_args()
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
