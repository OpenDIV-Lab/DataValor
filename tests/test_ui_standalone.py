from __future__ import annotations

from pathlib import Path

from UI.build_standalone import build_standalone, standalone_payload


def test_standalone_payload_contains_current_catalogs() -> None:
    payload = standalone_payload()

    assert len(payload["scenarios"]) >= 8
    assert {"real-nyc-mobility", "real-pjm-energy", "real-mimic-rwe", "real-sec-fred-investment"} <= {
        scenario["scenario_id"] for scenario in payload["scenarios"]
    }
    assert all("offline_participants" in scenario for scenario in payload["scenarios"])
    assert "audio" in payload["schemas"]["evaluation"]["modalities"]
    assert len(payload["schemas"]["valuation"]["methods"]) >= 10
    assert payload["components"]


def test_build_standalone_inlines_all_runtime_assets(tmp_path: Path) -> None:
    output = tmp_path / "datavalor-standalone.html"

    result = build_standalone(output)
    html = output.read_text(encoding="utf-8")

    assert result == output
    assert "window.DATAVALOR_STANDALONE" in html
    assert "const OfflineExecutionEngine" in html
    assert "const OfflineWorkbench" in html
    assert html.index("const OfflineExecutionEngine") < html.index("const OfflineWorkbench")
    assert '<script src="' not in html
    assert 'href="styles.css"' not in html
    assert "closeParticipantDialog" in html
    assert "valuation.time_decay" in html
    assert "工业传感数据采购" in html
