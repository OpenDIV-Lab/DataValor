"""DataValor CLI rebuilt around the public pipeline and registry contracts."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

from datavalor.core import RunContext
from datavalor.data_eval import EvaluationRequest, LexicalDiversityMetric
from datavalor.data_gov import adapter_from_uri


def load_config(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if target.suffix.lower() == ".json":
        value = json.loads(text)
    else:
        try:
            import yaml
        except ImportError as exc:
            raise RuntimeError("YAML CLI configuration requires PyYAML") from exc
        value = yaml.safe_load(text)
    if not isinstance(value, dict):
        raise ValueError("DataValor configuration must be a mapping")
    return value


def load_plugin(path: str | Path) -> dict[str, Any]:
    """Load a local extension module without assuming a source-project protocol."""
    target = Path(path)
    spec = importlib.util.spec_from_file_location(f"datavalor_plugin_{target.stem}", target)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load plugin {target}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {name: getattr(module, name) for name in dir(module) if not name.startswith("_")}


def cmd_profile(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    uri = config.get("uri") or config.get("data", {}).get("uri")
    if not uri:
        raise ValueError("profile configuration requires uri")
    rows = adapter_from_uri(uri).materialize()
    result = {"record_count": len(rows), "fields": sorted({key for row in rows for key in row})}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"DataValor profile written to {args.output}")
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    uri = config.get("uri") or config.get("data", {}).get("uri")
    rows = adapter_from_uri(uri).materialize()
    product = config.get("product", {})
    from datavalor.core import DataProduct, DataReference

    data_product = DataProduct(product.get("product_id", "product"), product.get("title", "DataValor product"), DataReference(uri, "jsonl"), product.get("owner_id", "owner"))
    metric = LexicalDiversityMetric(config.get("text_field", "text"))
    result = metric.compute(data_product, EvaluationRequest(options={"records": rows}), RunContext(args.run_id))
    Path(args.output).write_text(json.dumps({"name": result.name, "value": result.value, "statistics": dict(result.statistics)}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"DataValor evaluation written to {args.output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="datavalor", description="DataValor 数据估值与价值化工具")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, handler in (("profile", cmd_profile), ("evaluate", cmd_evaluate)):
        command = sub.add_parser(name)
        command.add_argument("--config", required=True)
        command.add_argument("--output", required=True)
        command.add_argument("--run-id", default="cli-run")
        command.add_argument("--plugin-file", action="append", default=[])
        command.set_defaults(func=handler)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    for path in args.plugin_file:
        load_plugin(path)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
