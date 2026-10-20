"""Generate the DataValor layered architecture figure using only the stdlib.

The SVG is intentionally generated from code so that module names, relations,
colors, and layout remain reviewable in version control. Run this file after
editing the diagram, or pass ``--check`` in CI to detect a stale SVG.
"""

from __future__ import annotations

import argparse
import html
from dataclasses import dataclass
from pathlib import Path


WIDTH = 1760
HEIGHT = 1280
OUTPUT = Path(__file__).with_name("datavalor-architecture.svg")
FONT = "Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
MONO = "'SFMono-Regular', Consolas, 'Liberation Mono', monospace"


@dataclass(frozen=True)
class Card:
    x: int
    y: int
    width: int
    height: int
    title: str
    path: str
    lines: tuple[str, ...]
    theme: str
    shape: str = "round"


THEMES = {
    "input": ("#EEF2FF", "#E0E7FF", "#4F46E5", "#312E81"),
    "gov": ("#EFF6FF", "#DBEAFE", "#2563EB", "#1E3A8A"),
    "prof": ("#ECFEFF", "#CFFAFE", "#0891B2", "#164E63"),
    "eval": ("#F0FDFA", "#CCFBF1", "#0D9488", "#134E4A"),
    "value": ("#FAF5FF", "#EDE9FE", "#7C3AED", "#4C1D95"),
    "price": ("#FFF7ED", "#FFEDD5", "#EA580C", "#7C2D12"),
    "market": ("#FFF1F2", "#FFE4E6", "#E11D48", "#881337"),
    "query": ("#F0FDF4", "#DCFCE7", "#16A34A", "#14532D"),
    "outcome": ("#F7FEE7", "#ECFCCB", "#65A30D", "#365314"),
    "feedback": ("#FFFBEB", "#FEF3C7", "#D97706", "#78350F"),
    "core": ("#F8FAFC", "#E2E8F0", "#334155", "#0F172A"),
    "toolkit": ("#F5F3FF", "#EDE9FE", "#6D28D9", "#3B0764"),
    "external": ("#FFFFFF", "#F8FAFC", "#64748B", "#334155"),
}


def escape(value: str) -> str:
    return html.escape(value, quote=True)


def text_element(
    x: float,
    y: float,
    value: str,
    *,
    size: int = 16,
    weight: int = 500,
    fill: str = "#334155",
    anchor: str = "start",
    family: str = FONT,
    opacity: float = 1.0,
) -> str:
    return (
        f'<text x="{x}" y="{y}" text-anchor="{anchor}" '
        f'font-family="{family}" font-size="{size}" font-weight="{weight}" '
        f'fill="{fill}" opacity="{opacity}">{escape(value)}</text>'
    )


def panel(y: int, height: int, label: str, index: str, fill: str, stroke: str) -> str:
    return "\n".join(
        [
            f'<rect x="40" y="{y}" width="1680" height="{height}" rx="28" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="1.2"/>',
            f'<rect x="54" y="{y + 18}" width="42" height="24" rx="12" fill="{stroke}"/>',
            text_element(75, y + 35, index, size=12, weight=800, fill="#FFFFFF", anchor="middle"),
            text_element(108, y + 36, label, size=15, weight=750, fill="#334155"),
        ]
    )


def panel_header(y: int, label: str, index: str, fill: str, stroke: str) -> str:
    width = max(250, len(label) * 9 + 92)
    return "\n".join(
        [
            f'<rect x="50" y="{y + 12}" width="{width}" height="36" rx="18" fill="{fill}"/>',
            f'<rect x="54" y="{y + 18}" width="42" height="24" rx="12" fill="{stroke}"/>',
            text_element(75, y + 35, index, size=12, weight=800, fill="#FFFFFF", anchor="middle"),
            text_element(108, y + 36, label, size=15, weight=750, fill="#334155"),
        ]
    )


def rounded_card(card: Card) -> str:
    light, pale, accent, dark = THEMES[card.theme]
    gid = f"grad-{card.theme}"
    x, y, w, h = card.x, card.y, card.width, card.height
    if card.shape == "chamfer":
        points = (
            f"{x + 18},{y} {x + w - 18},{y} {x + w},{y + 18} "
            f"{x + w},{y + h - 18} {x + w - 18},{y + h} {x + 18},{y + h} "
            f"{x},{y + h - 18} {x},{y + 18}"
        )
        base = (
            f'<polygon points="{points}" fill="url(#{gid})" stroke="{accent}" '
            'stroke-width="1.5" filter="url(#shadow)"/>'
        )
    else:
        dash = ' stroke-dasharray="8 6"' if card.shape == "external" else ""
        base = (
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="20" '
            f'fill="url(#{gid})" stroke="{accent}" stroke-width="1.5"{dash} '
            'filter="url(#shadow)"/>'
        )

    pieces = [base]
    if card.shape != "external":
        pieces.append(f'<rect x="{x}" y="{y}" width="7" height="{h}" rx="3.5" fill="{accent}"/>')
    pieces.append(text_element(x + 24, y + 31, card.path, size=12, weight=650, fill=accent, family=MONO))
    pieces.append(text_element(x + 24, y + 59, card.title, size=22, weight=760, fill=dark))
    line_y = y + 84
    for line in card.lines:
        pieces.append(text_element(x + 24, line_y, line, size=14, weight=500, fill="#475569"))
        line_y += 20
    return "\n".join(pieces)


def edge(
    path: str,
    *,
    color: str,
    marker: str,
    label: str | None = None,
    label_x: int = 0,
    label_y: int = 0,
    dashed: bool = False,
    width: float = 2.2,
) -> str:
    dash = ' stroke-dasharray="8 7"' if dashed else ""
    return (
        f'<path d="{path}" fill="none" stroke="{color}" stroke-width="{width}" '
        f'stroke-linecap="round" stroke-linejoin="round"{dash} '
        f'marker-end="url(#{marker})" opacity="0.92"/>'
    )


def edge_label(label: str, x: int, y: int, color: str) -> str:
    label_width = max(92, len(label) * 7 + 22)
    return "\n".join(
        [
            f'<rect x="{x - label_width / 2}" y="{y - 14}" '
            f'width="{label_width}" height="23" rx="11.5" fill="#FFFFFF" '
            f'stroke="{color}" stroke-width="0.8" opacity="0.98"/>',
            text_element(x, y + 2, label, size=11, weight=700, fill=color, anchor="middle"),
        ]
    )


def build_svg() -> str:
    cards = [
        Card(70, 130, 360, 125, "Data assets & versions", "INPUT / DATA", (
            "DataProduct • DataReference • schema", "checksum • provenance • version delta",
        ), "input"),
        Card(470, 130, 360, 125, "Research context", "INPUT / CONTEXT", (
            "RunContext • TaskContext • CostContext", "RightsBundle • seed • assumptions",
        ), "input"),
        Card(870, 130, 360, 125, "Actors & market reports", "INPUT / ECONOMY", (
            "buyers • sellers • bids • reserves", "budgets • quantities • realized demand",
        ), "input"),
        Card(1270, 130, 420, 125, "Optional ecosystems", "ADAPTER BOUNDARY", (
            "DataHub • Cleanlab • PyDVL • OpenDataVal", "Ocean • Mesa • PySyft • DB-GPT • Vanna",
        ), "external", shape="external"),
        Card(90, 350, 420, 130, "DataGov", "datavalor.data_gov", (
            "metadata catalog • rights matrix • security", "lineage graph • version diff • market readiness",
        ), "gov"),
        Card(670, 350, 420, 130, "DataProf", "datavalor.data_prof", (
            "robust statistics • entropy • correlation", "PSI / JS drift • coverage • rarity • joinability",
        ), "prof"),
        Card(1250, 350, 420, 130, "DataEval", "datavalor.data_eval", (
            "quality constraints • multimodal metrics", "task utility • demand fit • confidence gates",
        ), "eval"),
        Card(90, 590, 420, 130, "DataValue", "datavalor.data_value", (
            "task / risk / market-conditioned valuation", "LOO • Shapley • Banzhaf • portfolio selection",
        ), "value"),
        Card(670, 590, 420, 130, "DataPrice", "datavalor.data_price", (
            "cost / value / usage / demand pricing", "posted price • VCG • McAfee • procurement",
        ), "price"),
        Card(1250, 590, 420, 130, "DataMarket", "datavalor.data_market", (
            "catalog • matching • admission • allocation", "revenue sharing • strategy & shock simulation",
        ), "market"),
        Card(90, 850, 420, 120, "DataQuery", "datavalor.data_query", (
            "authorize → plan → execute → guard", "usage logging • governed agent boundary",
        ), "query"),
        Card(670, 850, 420, 120, "Realized outcomes", "OBSERVED ARTIFACTS", (
            "allocation • payment • welfare • revenue", "quality delivered • queries • downstream utility",
        ), "outcome", shape="chamfer"),
        Card(1250, 850, 420, 120, "Feedback & calibration", "CLOSED LOOP", (
            "acceptance probability • demand response", "usage anomaly • quote & valuation calibration",
        ), "feedback"),
        Card(90, 1095, 700, 120, "Core runtime & contracts", "datavalor.core", (
            "typed requests/results • Registry • PipelineRunner", "ArtifactEnvelope • lineage refs • ArtifactStore • diagnostics",
        ), "core"),
        Card(850, 1095, 480, 120, "Benchmark & analysis toolkit", "datavalor.toolkit", (
            "case × method × seed matrix • perturbations", "bootstrap • paired comparison • regret • Pareto frontier",
        ), "toolkit"),
        Card(1390, 1095, 280, 120, "DataMechBench", "SEPARATE BRANCH", (
            "settings • adapters • leaderboards", "consumes public mechanism APIs",
        ), "external", shape="external"),
    ]

    definitions = [
        "<defs>",
        '<linearGradient id="canvas" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#F8FAFC"/><stop offset="0.52" stop-color="#FFFFFF"/>'
        '<stop offset="1" stop-color="#F1F5F9"/></linearGradient>',
        '<filter id="shadow" x="-20%" y="-20%" width="140%" height="150%">'
        '<feDropShadow dx="0" dy="5" stdDeviation="7" flood-color="#0F172A" flood-opacity="0.10"/>'
        '</filter>',
    ]
    for name, (light, pale, _accent, _dark) in THEMES.items():
        definitions.append(
            f'<linearGradient id="grad-{name}" x1="0" y1="0" x2="1" y2="1">'
            f'<stop offset="0" stop-color="{light}"/><stop offset="1" stop-color="{pale}"/>'
            "</linearGradient>"
        )
    for marker, color in {
        "arrow-data": "#475569",
        "arrow-control": "#2563EB",
        "arrow-evidence": "#0F766E",
        "arrow-economic": "#7C3AED",
        "arrow-market": "#E11D48",
        "arrow-feedback": "#D97706",
        "arrow-adapter": "#64748B",
    }.items():
        definitions.append(
            f'<marker id="{marker}" viewBox="0 0 10 10" refX="8.8" refY="5" '
            'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
            f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{color}"/></marker>'
        )
    definitions.append("</defs>")

    pieces = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title desc">',
        '<title id="title">DataValor layered architecture</title>',
        '<desc id="desc">A layered view of data governance, profiling, evaluation, valuation, pricing, '
        'market mechanisms, governed querying, feedback, shared contracts, adapters, and benchmark tooling.</desc>',
        *definitions,
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="url(#canvas)"/>',
        '<circle cx="1640" cy="65" r="170" fill="#DDD6FE" opacity="0.22"/>',
        '<circle cx="95" cy="1030" r="210" fill="#BFDBFE" opacity="0.16"/>',
        text_element(70, 58, "DataValor · Layered Architecture", size=30, weight=800, fill="#0F172A"),
        text_element(70, 84, "Evidence-aware data valuation, pricing, mechanism design, and market realization", size=16, weight=520, fill="#64748B"),
        text_element(1690, 58, "MAIN LIBRARY", size=12, weight=800, fill="#4F46E5", anchor="end", family=MONO),
        text_element(1690, 80, "typed artifacts · explicit assumptions · reproducible runs", size=12, weight=550, fill="#64748B", anchor="end"),
        panel(305, 215, "EVIDENCE & ELIGIBILITY", "01", "#F0FDFF", "#0E7490"),
        panel(545, 215, "VALUE FORMATION & MECHANISM DESIGN", "02", "#FCF7FF", "#7C3AED"),
        panel(805, 205, "MARKET REALIZATION & LEARNING", "03", "#F6FFF7", "#16A34A"),
        panel(1045, 175, "CROSS-CUTTING FOUNDATION", "04", "#F8FAFC", "#475569"),
    ]

    # Relationships are drawn before cards so card surfaces protect labels from line overlap.
    pieces.extend(
        [
            edge("M250 255 C250 300 300 305 300 350", color="#475569", marker="arrow-data", label="data + versions", label_x=285, label_y=294),
            edge("M350 255 L350 278 L880 278 L880 350", color="#475569", marker="arrow-data"),
            edge("M650 255 L650 289 L1460 289 L1460 350", color="#475569", marker="arrow-data", label="task & constraints", label_x=1060, label_y=286),
            edge("M1050 255 L1120 286 L1120 532 L880 532 L880 590", color="#E11D48", marker="arrow-market", label="bids / budgets", label_x=995, label_y=529),
            edge("M1120 255 L1190 295 L1190 536 L1460 536 L1460 590", color="#E11D48", marker="arrow-market"),
            edge("M1690 192 L1712 192 L1712 915 L1670 915", color="#64748B", marker="arrow-adapter", label="lazy adapters", label_x=1662, label_y=327, dashed=True),
            edge("M1712 415 L1670 415", color="#64748B", marker="arrow-adapter", dashed=True),
            edge("M1712 655 L1670 655", color="#64748B", marker="arrow-adapter", dashed=True),
            edge("M510 415 L670 415", color="#2563EB", marker="arrow-control", label="governed metadata", label_x=590, label_y=401),
            edge("M1090 415 L1250 415", color="#0F766E", marker="arrow-evidence", label="profile evidence", label_x=1170, label_y=401),
            edge("M90 420 L55 420 L55 910 L90 910", color="#2563EB", marker="arrow-control", label="authorization", label_x=104, label_y=793),
            edge("M430 480 L430 514 L1610 514 L1610 590", color="#2563EB", marker="arrow-control", label="rights & admission", label_x=1030, label_y=511),
            edge("M880 480 L880 526 L430 526 L430 590", color="#0F766E", marker="arrow-evidence", label="scarcity / coverage", label_x=650, label_y=523),
            edge("M1370 480 L1370 538 L300 538 L300 590", color="#0F766E", marker="arrow-evidence", label="quality & task utility", label_x=827, label_y=535),
            edge("M1460 480 L1460 554 L960 554 L960 590", color="#0F766E", marker="arrow-evidence", label="quality modifiers", label_x=1215, label_y=551),
            edge("M510 655 L670 655", color="#7C3AED", marker="arrow-economic", label="value estimate", label_x=590, label_y=642),
            edge("M1090 655 L1250 655", color="#E11D48", marker="arrow-market", label="quote / allocation", label_x=1170, label_y=642),
            edge("M430 720 L430 774 L1370 774 L1370 720", color="#7C3AED", marker="arrow-economic", label="contribution-aware revenue", label_x=900, label_y=771),
            edge("M1320 720 L1320 796 L300 796 L300 850", color="#E11D48", marker="arrow-market", label="transaction rights", label_x=805, label_y=793),
            edge("M1460 720 L1460 788 L880 788 L880 850", color="#E11D48", marker="arrow-market", label="allocation & payment", label_x=1170, label_y=785),
            edge("M510 910 L670 910", color="#16A34A", marker="arrow-evidence", label="guarded usage", label_x=590, label_y=897),
            edge("M1090 910 L1250 910", color="#65A30D", marker="arrow-feedback", label="observations", label_x=1170, label_y=897),
            edge("M1460 850 L1460 782 L1640 782 L1640 566 L960 566 L960 590", color="#D97706", marker="arrow-feedback", label="acceptance & demand", label_x=1315, label_y=563, dashed=True),
            edge("M1250 945 L1150 945 L1150 1026 L42 1026 L42 655 L90 655", color="#D97706", marker="arrow-feedback", label="realized utility / calibration", label_x=260, label_y=1023, dashed=True),
            edge("M880 970 L880 1032 L1040 1032 L1040 1095", color="#6D28D9", marker="arrow-economic", label="comparable observations", label_x=1010, label_y=1029),
            edge("M1460 970 L1460 1020 L1190 1020 L1190 1095", color="#6D28D9", marker="arrow-economic", dashed=True),
            edge("M1330 1155 L1390 1155", color="#64748B", marker="arrow-adapter", dashed=True),
        ]
    )

    # Redraw relation labels and layer headers after all paths. This keeps later
    # routes from cutting through text while retaining deterministic routing.
    pieces.extend(
        [
            edge_label("data + versions", 285, 294, "#475569"),
            edge_label("task & constraints", 1060, 286, "#475569"),
            edge_label("bids / budgets", 995, 529, "#E11D48"),
            edge_label("lazy adapters", 1662, 327, "#64748B"),
            edge_label("governed metadata", 590, 401, "#2563EB"),
            edge_label("profile evidence", 1170, 401, "#0F766E"),
            edge_label("authorization", 104, 793, "#2563EB"),
            edge_label("rights & admission", 1030, 511, "#2563EB"),
            edge_label("scarcity / coverage", 650, 523, "#0F766E"),
            edge_label("quality & task utility", 827, 535, "#0F766E"),
            edge_label("quality modifiers", 1215, 551, "#0F766E"),
            edge_label("value estimate", 590, 642, "#7C3AED"),
            edge_label("quote / allocation", 1170, 642, "#E11D48"),
            edge_label("contribution-aware revenue", 900, 771, "#7C3AED"),
            edge_label("transaction rights", 805, 793, "#E11D48"),
            edge_label("allocation & payment", 1170, 785, "#E11D48"),
            edge_label("guarded usage", 590, 897, "#16A34A"),
            edge_label("observations", 1170, 897, "#65A30D"),
            edge_label("acceptance & demand", 1315, 563, "#D97706"),
            edge_label("realized utility / calibration", 260, 1023, "#D97706"),
            edge_label("comparable observations", 1010, 1029, "#6D28D9"),
            panel_header(305, "EVIDENCE & ELIGIBILITY", "01", "#F0FDFF", "#0E7490"),
            panel_header(545, "VALUE FORMATION & MECHANISM DESIGN", "02", "#FCF7FF", "#7C3AED"),
            panel_header(805, "MARKET REALIZATION & LEARNING", "03", "#F6FFF7", "#16A34A"),
            panel_header(1045, "CROSS-CUTTING FOUNDATION", "04", "#F8FAFC", "#475569"),
        ]
    )

    pieces.extend(rounded_card(card) for card in cards)

    pieces.extend(
        [
            '<line x1="90" y1="1238" x2="125" y2="1238" stroke="#0F766E" stroke-width="2.4" marker-end="url(#arrow-evidence)"/>',
            text_element(136, 1243, "evidence / artifacts", size=12, weight=650, fill="#475569"),
            '<line x1="315" y1="1238" x2="350" y2="1238" stroke="#2563EB" stroke-width="2.4" marker-end="url(#arrow-control)"/>',
            text_element(361, 1243, "governance control", size=12, weight=650, fill="#475569"),
            '<line x1="548" y1="1238" x2="583" y2="1238" stroke="#7C3AED" stroke-width="2.4" marker-end="url(#arrow-economic)"/>',
            text_element(594, 1243, "economic signal", size=12, weight=650, fill="#475569"),
            '<line x1="766" y1="1238" x2="801" y2="1238" stroke="#E11D48" stroke-width="2.4" marker-end="url(#arrow-market)"/>',
            text_element(812, 1243, "market outcome", size=12, weight=650, fill="#475569"),
            '<line x1="985" y1="1238" x2="1020" y2="1238" stroke="#D97706" stroke-width="2.4" stroke-dasharray="8 7" marker-end="url(#arrow-feedback)"/>',
            text_element(1031, 1243, "feedback loop", size=12, weight=650, fill="#475569"),
            '<line x1="1196" y1="1238" x2="1231" y2="1238" stroke="#64748B" stroke-width="2.4" stroke-dasharray="8 7" marker-end="url(#arrow-adapter)"/>',
            text_element(1242, 1243, "optional / external boundary", size=12, weight=650, fill="#475569"),
            text_element(1690, 1268, "generated from docs/assets/generate_architecture.py", size=11, weight=550, fill="#94A3B8", anchor="end", family=MONO),
            "</svg>",
        ]
    )
    return "\n".join(pieces) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the committed SVG is stale")
    args = parser.parse_args()
    rendered = build_svg()
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != rendered:
            raise SystemExit(f"{OUTPUT} is stale; regenerate it with {Path(__file__).name}")
        print(f"up to date: {OUTPUT}")
        return 0
    OUTPUT.write_text(rendered, encoding="utf-8")
    print(f"wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
