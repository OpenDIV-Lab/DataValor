from __future__ import annotations

from html.parser import HTMLParser
import json
from pathlib import Path
import re
import struct
import subprocess
from urllib.parse import urlparse

from UI.server.app import create_app


class TourDocument(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.text: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.case_tabs: list[dict[str, str | None]] = []
        self.stage_tabs: list[dict[str, str | None]] = []
        self.ids: set[str] = set()
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(str(values["id"]))
        if tag == "title":
            self._in_title = True
        if tag == "link" and values.get("href"):
            self.links.append(("style", str(values["href"])))
        if tag == "script" and values.get("src"):
            self.links.append(("script", str(values["src"])))
        if values.get("role") == "tab" and values.get("data-case"):
            self.case_tabs.append(values)
        if values.get("role") == "tab" and values.get("data-stage"):
            self.stage_tabs.append(values)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        cleaned = " ".join(data.split())
        if not cleaned:
            return
        self.text.append(cleaned)
        if self._in_title:
            self.title += cleaned


def load_tour(tmp_path: Path) -> tuple[Path, TourDocument, str]:
    app = create_app(tmp_path / "workspace")
    static_mount = next(route for route in app.routes if route.path == "")
    ui_root = Path(static_mount.app.directory)
    html_path = ui_root / "tour" / "index.html"
    html = html_path.read_text(encoding="utf-8")
    document = TourDocument()
    document.feed(html)
    return html_path.parent, document, html


def test_product_tour_is_a_separate_served_ui(tmp_path: Path) -> None:
    tour_root, document, _ = load_tour(tmp_path)

    assert document.title == "DataValor · 从数据到市场决策"
    assert {kind for kind, _ in document.links} == {"style", "script"}
    for kind, reference in document.links:
        parsed = urlparse(reference)
        assert not parsed.scheme and not parsed.netloc
        asset = tour_root / reference
        assert asset.is_file(), (kind, reference)
        assert asset.stat().st_size > 0


def test_product_tour_explains_the_default_case_without_javascript(tmp_path: Path) -> None:
    _, document, html = load_tour(tmp_path)
    readable = " ".join(document.text)

    assert len(document.case_tabs) == 1
    assert len(document.stage_tabs) == 6
    assert "金融投研数据采购" in readable
    assert "SEC EDGAR" in readable
    assert "CounterfactualValuator" in readable
    assert "SubscriptionPricingModel" in readable
    assert "BundleDemandMatcher" in readable
    assert "PJM 负荷数据订阅" in readable
    assert "临床 RWE 数据许可" in readable
    assert "NYC 出行需求数据采购" in readable
    assert "估值不是成交价" in readable
    assert "data-decision-receipt" in html
    assert "<noscript>" in html


def test_product_tour_controls_expose_accessible_selection_state(tmp_path: Path) -> None:
    _, document, html = load_tour(tmp_path)

    assert sum(tab.get("aria-selected") == "true" for tab in document.case_tabs) == 1
    assert sum(tab.get("aria-selected") == "true" for tab in document.stage_tabs) == 1
    assert all(tab.get("aria-controls") for tab in [*document.case_tabs, *document.stage_tabs])
    assert {"casePanel", "stagePanel", "decisionReceipt", "artifactLineage"} <= document.ids
    tablist = html.split('<div class="case-tabs" role="tablist"', 1)[1].split("</div>", 1)[0]
    assert "secondary-case" not in tablist
    assert 'class="secondary-case-links"' in html


def evaluate_tour_javascript(expression: str) -> object:
    root = Path(__file__).parents[1]
    command = (
        "require('./UI/tour/tour.js');"
        f"process.stdout.write(JSON.stringify({expression}));"
    )
    result = subprocess.run(
        ["node", "-e", command],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_product_tour_model_covers_real_cases_and_value_stages() -> None:
    model = evaluate_tour_javascript("globalThis.DataValorTour.model")

    assert set(model["cases"]) == {
        "real-sec-fred-investment",
        "real-pjm-energy",
        "real-mimic-rwe",
        "real-nyc-mobility",
    }
    assert set(model["stages"]) == {"govern", "evaluate", "value", "price", "market", "realize"}
    for case in model["cases"].values():
        assert {"buyer", "sellers", "task", "products", "valuation", "pricing", "market", "budget", "sources", "signals", "sourceNote"} <= case.keys()
    for stage in model["stages"].values():
        assert len(stage["inputs"]) >= 2
        assert stage["method"]
        assert len(stage["outputs"]) >= 2
        assert len(stage["metrics"]) == 3
        assert stage["artifact"]


def test_product_tour_keyboard_navigation_wraps_tabs() -> None:
    transitions = evaluate_tour_javascript("[DataValorTour.nextTabIndex(0, 4, 'ArrowLeft'), DataValorTour.nextTabIndex(3, 4, 'ArrowRight'), DataValorTour.nextTabIndex(1, 4, 'Home'), DataValorTour.nextTabIndex(1, 4, 'End')]")

    assert transitions == [3, 0, 0, 3]


def test_case_specific_methods_keep_matching_explanations() -> None:
    cases = evaluate_tour_javascript("globalThis.DataValorTour.model.cases")
    expected_formula_fragments = {
        ("real-sec-fred-investment", "value"): "U(task | data)",
        ("real-sec-fred-investment", "price"): "period_fee",
        ("real-sec-fred-investment", "market"): "bundle",
        ("real-pjm-energy", "value"): "delivery_probability",
        ("real-pjm-energy", "price"): "P(accept",
        ("real-pjm-energy", "market"): "quality",
        ("real-mimic-rwe", "value"): "λ",
        ("real-mimic-rwe", "price"): "rights",
        ("real-mimic-rwe", "market"): "w_price",
    }

    for (case_id, stage_id), fragment in expected_formula_fragments.items():
        case = cases[case_id]
        detail = case["methodDetails"][stage_id]
        assert detail["method"] == case["methods"][stage_id]
        assert fragment in detail["formula"]
        assert detail["note"]
    assert cases["real-nyc-mobility"]["methods"]["realize"] == "UsageAggregator"


def test_capability_matrix_labels_usage_aggregator_as_the_method(tmp_path: Path) -> None:
    _, _, html = load_tour(tmp_path)

    assert "<code>UsageAggregator</code>" in html


def test_every_case_has_a_complete_six_stage_operator_scene() -> None:
    cases = evaluate_tour_javascript("globalThis.DataValorTour.model.cases")
    stage_ids = {"govern", "evaluate", "value", "price", "market", "realize"}
    expected_artifacts = {
        "govern": "GovernanceReport",
        "evaluate": "EvaluationReport",
        "value": "ValuationReport",
        "price": "PriceQuote",
        "market": "PricingOutcome",
        "realize": "UsageAggregate",
    }

    for case in cases.values():
        assert set(case["scenes"]) == stage_ids
        for stage_id, scene in case["scenes"].items():
            assert {"id", "operator", "selection", "status"} <= scene["run"].keys()
            for pane_name in ("input", "config", "output"):
                pane = scene[pane_name]
                assert pane["title"]
                assert pane["meta"]
                assert len(pane["rows"]) >= 3
                assert all({"label", "value"} <= row.keys() for row in pane["rows"])
            assert scene["output"]["artifact"] == expected_artifacts[stage_id]


def test_financial_walkthrough_contains_concrete_records_parameters_and_decisions() -> None:
    scenes = evaluate_tour_javascript(
        "globalThis.DataValorTour.model.cases['real-sec-fred-investment'].scenes"
    )
    serialized = json.dumps(scenes, ensure_ascii=False)

    assert "0000320193" in serialized
    assert "2024-11-01" in serialized
    assert "Rank IC" in serialized
    assert "CounterfactualValuator" in serialized
    assert "USD 161,920" in serialized
    assert "USD 260,000" in serialized
    assert "SEC + FRED + PIT Signals" in serialized
    assert "renewal_candidate" in serialized


def test_financial_quote_payment_and_surplus_reconcile() -> None:
    scenes = evaluate_tour_javascript(
        "globalThis.DataValorTour.model.cases['real-sec-fred-investment'].scenes"
    )
    quote = {row["label"]: row["value"] for row in scenes["price"]["output"]["rows"]}
    outcome = {row["label"]: row["value"] for row in scenes["market"]["output"]["rows"]}

    assert quote["base + SLA"] == "USD 176,000"
    assert quote["commitment discount"] == "− USD 14,080"
    assert quote["annual quote"] == "USD 161,920"
    assert outcome["buyer payment"] == "USD 161,920"
    assert outcome["estimated buyer surplus"] == "USD 33,080"
    assert 176_000 - 14_080 == 161_920
    assert 195_000 - 161_920 == 33_080


def test_energy_pricing_separates_selected_quote_from_expected_revenue() -> None:
    output = evaluate_tour_javascript(
        "globalThis.DataValorTour.model.cases['real-pjm-energy'].scenes.price.output.rows"
    )
    rows = {row["label"]: row for row in output}

    assert rows["selected annual quote"]["value"] == "USD 138,000"
    assert rows["expected revenue"]["value"] == "USD 97,980"
    assert "P(accept)=0.71" in rows["expected revenue"]["detail"]


def test_clinical_demo_volume_matches_the_named_physionet_subset() -> None:
    case = evaluate_tour_javascript(
        "globalThis.DataValorTour.model.cases['real-mimic-rwe']"
    )
    serialized = json.dumps(case["scenes"], ensure_ascii=False)

    assert "100-patient demo subset" in serialized
    assert "73,181 admissions" not in serialized


def test_actual_workbench_screens_cover_config_and_result_for_every_guided_stage() -> None:
    root = Path(__file__).parents[1] / "UI" / "tour" / "assets" / "workbench"
    stages = {"governance", "evaluation", "valuation", "pricing", "market", "resources"}

    for stage in stages:
        for mode in ("config", "result"):
            image = root / f"{stage}-{mode}.png"
            assert image.is_file(), image
            assert image.stat().st_size > 150_000, image
            payload = image.read_bytes()[:24]
            assert payload[:8] == b"\x89PNG\r\n\x1a\n", image
            width, height = struct.unpack(">II", payload[16:24])
            assert (width, height) == (1600, 1100), image


def test_default_tour_embeds_the_actual_valuation_workbench_instead_of_a_simulated_ui(tmp_path: Path) -> None:
    _, document, html = load_tour(tmp_path)
    readable = " ".join(document.text)

    assert {
        "workbenchScreen",
        "workbenchScreenLink",
        "screenConfigButton",
        "screenResultButton",
        "screenInputText",
        "screenConfigText",
        "screenOutputText",
    } <= document.ids
    assert 'src="assets/workbench/valuation-config.png"' in html
    assert "真实工作台 · 数据估值配置" in readable
    assert "valuation.counterfactual" in readable
    assert "stage-workbench" not in html
    assert "data-scene-pane" not in html


def test_financial_stage_screens_pair_actual_config_and_result_with_direct_guidance() -> None:
    scenes = evaluate_tour_javascript(
        "globalThis.DataValorTour.model.cases['real-sec-fred-investment'].scenes"
    )
    expected_files = {
        "govern": "governance",
        "evaluate": "evaluation",
        "value": "valuation",
        "price": "pricing",
        "market": "market",
        "realize": "resources",
    }

    for stage_id, filename in expected_files.items():
        screen = scenes[stage_id]["screen"]
        assert screen["config"] == f"assets/workbench/{filename}-config.png"
        assert screen["result"] == f"assets/workbench/{filename}-result.png"
        assert screen["title"]
        assert screen["input"]
        assert screen["configuration"]
        assert screen["output"]
        assert "DataValor 工作台" in screen["alt"]


def test_screen_state_switches_image_and_caption_without_mixing_modes() -> None:
    states = evaluate_tour_javascript(
        "(() => { const scene = DataValorTour.model.cases['real-sec-fred-investment'].scenes.price; "
        "return [DataValorTour.screenState(scene, 'config'), DataValorTour.screenState(scene, 'result')]; })()"
    )

    assert states[0]["src"].endswith("pricing-config.png")
    assert states[0]["modeLabel"] == "配置界面"
    assert states[1]["src"].endswith("pricing-result.png")
    assert states[1]["modeLabel"] == "执行结果"
    assert states[0]["caption"] != states[1]["caption"]


def test_tour_type_is_readable_without_tiny_labels() -> None:
    css = (Path(__file__).parents[1] / "UI" / "tour" / "tour.css").read_text(encoding="utf-8")

    assert "body { margin: 0; overflow-x: hidden; color: var(--ink); background: var(--bg); font-size: 18px" in css
    assert ".screen-explainer p" in css and "font-size: 16px" in css
    tiny_sizes = [int(value) for value in re.findall(r"font-size:\s*(\d+)px", css) if int(value) < 12]
    assert tiny_sizes == []
    for selector in (".receipt-decision p", ".source-stamp p", ".noscript-note"):
        match = re.search(rf"{re.escape(selector)}\s*\{{[^}}]*font-size:\s*(\d+)px", css)
        assert match and int(match.group(1)) >= 16, selector
