from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .services.components import component_catalog
from .services.evaluation_workbench import evaluation_schema
from .services.market_workbench import market_schema
from .services.pricing_workbench import pricing_schema
from .services.scenarios import _scenario_participants, scenario_catalog
from .services.valuation_workbench import valuation_schema


UI_ROOT = Path(__file__).resolve().parent


def standalone_payload() -> dict[str, Any]:
    scenarios = scenario_catalog()
    for scenario in scenarios:
        scenario["offline_participants"] = _scenario_participants(scenario)
    return {
        "format": "datavalor-standalone-v1",
        "scenarios": scenarios,
        "schemas": {
            "evaluation": evaluation_schema(),
            "valuation": valuation_schema(),
            "pricing": pricing_schema(),
            "market": market_schema(),
        },
        "components": component_catalog(),
    }


def _script(source: str) -> str:
    return source.replace("</script", "<\\/script")


def build_standalone(output: str | Path | None = None) -> Path:
    output_path = Path(output) if output is not None else UI_ROOT / "datavalor-standalone.html"
    html = (UI_ROOT / "index.html").read_text(encoding="utf-8")
    css = (UI_ROOT / "styles.css").read_text(encoding="utf-8")
    data = json.dumps(standalone_payload(), ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")

    html = html.replace('<link rel="stylesheet" href="styles.css">', f"<style>\n{css}\n</style>")
    script_tags = '\n  <script src="workbench-api.js"></script>\n  <script src="app.js"></script>'
    inline_scripts = "\n".join([
        f"  <script>window.DATAVALOR_STANDALONE = {data};</script>",
        f"  <script>\n{_script((UI_ROOT / 'offline-engine.js').read_text(encoding='utf-8'))}\n  </script>",
        f"  <script>\n{_script((UI_ROOT / 'offline-workbench.js').read_text(encoding='utf-8'))}\n  </script>",
        f"  <script>\n{_script((UI_ROOT / 'workbench-api.js').read_text(encoding='utf-8'))}\n  </script>",
        f"  <script>\n{_script((UI_ROOT / 'app.js').read_text(encoding='utf-8'))}\n  </script>",
    ])
    if script_tags not in html:
        raise ValueError("index.html runtime script block was not found")
    html = html.replace(script_tags, "\n" + inline_scripts)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the offline DataValor Workbench as one HTML file.")
    parser.add_argument("output", nargs="?", type=Path, default=UI_ROOT / "datavalor-standalone.html")
    args = parser.parse_args()
    path = build_standalone(args.output)
    print(path)


if __name__ == "__main__":
    main()
