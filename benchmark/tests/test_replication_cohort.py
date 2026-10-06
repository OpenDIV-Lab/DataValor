from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import yaml
from datamechbench.data import load_owner_dataset
from datamechbench.replication import (
    analyze_replication_wave,
    audit_replication_protocol,
)
from datamechbench.settings.heldout import make_heldout_valuation_cases

REPOSITORY_ROOT = Path(__file__).parents[2]
BENCHMARK_ROOT = REPOSITORY_ROOT / "benchmark"
CONFIG = BENCHMARK_ROOT / "configs" / "kdd_heldout_replication_v2.yaml"
PROTOCOL = BENCHMARK_ROOT / "evidence" / "kdd_heldout_replication_protocol_v1.json"
V1_MANIFEST = BENCHMARK_ROOT / "evidence" / "kdd_heldout_confirmatory_v1.json"


def _load_script(name: str):
    path = BENCHMARK_ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(f"test_{name.removesuffix('.py')}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_yaml(path: Path, payload: object) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def test_frozen_v2_replication_protocol_is_disjoint_and_claim_preserving() -> None:
    audit = audit_replication_protocol(
        CONFIG,
        PROTOCOL,
        V1_MANIFEST,
        REPOSITORY_ROOT,
    )

    assert audit.errors == ()
    assert audit.replication_wave == "v2"
    assert audit.block_counts == {
        "valuation": 2,
        "procurement": 2,
        "trading": 2,
    }
    assert audit.headline_method_count == 17
    assert audit.contrast_ids == (
        "V-BANZHAF-vs-SHAPLEY",
        "V-RVSV-vs-VSV",
        "P-CGLR-vs-GPS",
        "P-JTDEOM-vs-GPS",
        "T-MCAFEE-vs-TR",
        "T-SBBA-vs-TR",
    )
    assert audit.random_seeds == (1701, 2903, 4703)


def test_replication_protocol_rejects_v1_source_overlap(tmp_path: Path) -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    config["sources"]["valuation"][0]["openml_id"] = 44
    config["sources"]["valuation"][0]["block_id"] = "VHO-spambase"
    changed = tmp_path / "overlap.yaml"
    _write_yaml(changed, config)

    audit = audit_replication_protocol(
        changed,
        PROTOCOL,
        V1_MANIFEST,
        REPOSITORY_ROOT,
    )

    assert "v1_source_overlap:valuation:openml_id:44" in audit.errors
    assert "v1_block_overlap:valuation:VHO-spambase" in audit.errors
    assert "config_protocol_mismatch:sources" in audit.errors


def test_replication_protocol_rejects_unsafe_source_path(tmp_path: Path) -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    config["sources"]["valuation"][0]["raw_filename"] = "../escape.arff"
    changed = tmp_path / "unsafe.yaml"
    _write_yaml(changed, config)

    audit = audit_replication_protocol(
        changed,
        PROTOCOL,
        V1_MANIFEST,
        REPOSITORY_ROOT,
    )

    assert "unsafe_source_path:valuation:../escape.arff" in audit.errors
    assert "config_protocol_mismatch:sources" in audit.errors


def test_replication_protocol_rejects_tampered_freeze(tmp_path: Path) -> None:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    tampered = copy.deepcopy(protocol)
    tampered["headline_methods"]["trading"] = tampered["headline_methods"][
        "trading"
    ][:-1]
    marker = tmp_path / "tampered.json"
    marker.write_text(json.dumps(tampered), encoding="utf-8")

    audit = audit_replication_protocol(
        CONFIG,
        marker,
        V1_MANIFEST,
        REPOSITORY_ROOT,
    )

    assert "invalid_protocol_hash" in audit.errors
    assert "config_protocol_mismatch:headline_methods" in audit.errors


def test_replication_protocol_rejects_changed_estimand_and_seed_panel(
    tmp_path: Path,
) -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    config["contrasts"][0]["estimand"] = "row_mean"
    config["random_seeds"] = [7]
    changed = tmp_path / "changed-claims.yaml"
    _write_yaml(changed, config)

    audit = audit_replication_protocol(
        changed,
        PROTOCOL,
        V1_MANIFEST,
        REPOSITORY_ROOT,
    )

    assert "v1_contrast_mismatch" in audit.errors
    assert "config_protocol_mismatch:contrasts" in audit.errors
    assert "seed_panel_not_frozen" in audit.errors


def test_confirmation_cli_exposes_native_path_overrides(tmp_path: Path) -> None:
    runner = _load_script("run_kdd_heldout_confirmation.py")

    args = runner.parse_args([
        "--config", str(tmp_path / "config.yaml"),
        "--protocol", str(tmp_path / "protocol.json"),
        "--output", str(tmp_path / "output"),
        "--manifest", str(tmp_path / "manifest.json"),
        "--data-root", str(tmp_path / "data"),
        "--run-name", "replication-v2",
        "--reuse-results",
    ])

    assert args.config == tmp_path / "config.yaml"
    assert args.protocol == tmp_path / "protocol.json"
    assert args.output == tmp_path / "output"
    assert args.manifest == tmp_path / "manifest.json"
    assert args.data_root == tmp_path / "data"
    assert args.run_name == "replication-v2"
    assert args.reuse_results is True


def test_confirmation_cli_preserves_v1_defaults() -> None:
    runner = _load_script("run_kdd_heldout_confirmation.py")

    args = runner.parse_args([])

    assert args.config == BENCHMARK_ROOT / "configs" / "kdd_heldout_confirmatory.yaml"
    assert args.protocol == BENCHMARK_ROOT / "evidence" / "kdd_heldout_protocol_v6.json"
    assert args.output == BENCHMARK_ROOT / "outputs" / "kdd_heldout_confirmatory"
    assert args.manifest == V1_MANIFEST
    assert args.data_root == BENCHMARK_ROOT / "data" / "heldout"
    assert args.run_name == "datamechbench-kdd-heldout-v1"
    assert args.reuse_results is False


def test_replication_report_manifest_binds_frozen_v2_design() -> None:
    manifest = json.loads(
        (
            BENCHMARK_ROOT
            / "outputs"
            / "kdd_heldout_replication_v2"
            / "replication_manifest.json"
        ).read_text(encoding="utf-8")
    )

    assert manifest["inputs"]["v2_config"]["path"] == (
        "benchmark/configs/kdd_heldout_replication_v2.yaml"
    )
    assert manifest["inputs"]["v2_protocol"]["path"] == (
        "benchmark/evidence/kdd_heldout_replication_protocol_v1.json"
    )


def test_reuse_result_count_reads_nonempty_jsonl_rows(tmp_path: Path) -> None:
    runner = _load_script("run_kdd_heldout_confirmation.py")
    results = tmp_path / "results.jsonl"
    results.write_text('{"row": 1}\n\n{"row": 2}\n', encoding="utf-8")

    assert runner.result_row_count(results) == 2


def test_replication_run_cannot_overwrite_v1_outputs() -> None:
    runner = _load_script("run_kdd_heldout_confirmation.py")
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))

    try:
        runner.guard_output_separation(
            config,
            BENCHMARK_ROOT / "outputs" / "kdd_heldout_confirmatory",
            V1_MANIFEST,
        )
    except ValueError as error:
        assert "must not overwrite v1" in str(error)
    else:
        raise AssertionError("v2 replication was allowed to overwrite v1")


def test_v2_valuation_source_location_is_config_driven(tmp_path: Path) -> None:
    runner = _load_script("run_kdd_heldout_confirmation.py")
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    source = config["sources"]["valuation"][0]

    raw_path, target = runner.valuation_source_location(source, tmp_path)

    assert raw_path == tmp_path / "raw" / "openml" / "blood-transfusion-46913.arff"
    assert target == "DonatedBloodInMarch2007"


def test_relative_data_root_is_normalized_before_receipt_paths() -> None:
    runner = _load_script("run_kdd_heldout_confirmation.py")
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    source = config["sources"]["valuation"][0]

    raw_path, _ = runner.valuation_source_location(
        source,
        Path("benchmark/data/replication_v2"),
    )

    assert raw_path.is_absolute()
    assert raw_path.is_relative_to(REPOSITORY_ROOT)


def test_relative_artifact_path_is_normalized_to_repository_record() -> None:
    runner = _load_script("run_kdd_heldout_confirmation.py")

    record = runner._artifact(
        Path("benchmark/evidence/kdd_heldout_replication_protocol_v1.json")
    )

    assert record["path"] == (
        "benchmark/evidence/kdd_heldout_replication_protocol_v1.json"
    )
    assert len(record["sha256"]) == 64


def test_v2_valuation_cases_honor_explicit_block_ids() -> None:
    dataset = load_owner_dataset(seed=1701, dataset_name="wine")

    cases = make_heldout_valuation_cases(
        {"new-source": dataset},
        independent_blocks={"new-source": "VR2-explicit"},
    )

    assert len(cases) == 3
    assert {case.metadata["independent_block"] for case in cases} == {
        "VR2-explicit"
    }


def test_procurement_cli_accepts_v2_config_and_data_root(tmp_path: Path) -> None:
    processor = _load_script("process_chilecompra_bulk.py")

    args = processor.parse_args([
        "--config", str(tmp_path / "config.yaml"),
        "--protocol", str(tmp_path / "protocol.json"),
        "--snapshot", str(tmp_path / "snapshot.jsonl.gz"),
        "--data-root", str(tmp_path / "data"),
    ])

    assert args.config == tmp_path / "config.yaml"
    assert args.protocol == tmp_path / "protocol.json"
    assert args.snapshot == tmp_path / "snapshot.jsonl.gz"
    assert args.data_root == tmp_path / "data"


def _contrast(
    contrast_id: str,
    *,
    effect: float,
    ci_low: float,
    ci_high: float,
    blocks: tuple[float, ...],
    track: str = "valuation",
    decision: str = "boundary",
) -> dict[str, object]:
    return {
        "contrast_id": contrast_id,
        "track": track,
        "effect": effect,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "decision": decision,
        "independent_blocks": len(blocks),
        "block_effects": {
            f"{contrast_id}-block-{index}": value
            for index, value in enumerate(blocks, start=1)
        },
    }


def test_replication_analysis_keeps_waves_separate_and_classifies_direction() -> None:
    contrast_ids = (
        "V-BANZHAF-vs-SHAPLEY",
        "V-RVSV-vs-VSV",
        "P-CGLR-vs-GPS",
        "P-JTDEOM-vs-GPS",
        "T-MCAFEE-vs-TR",
        "T-SBBA-vs-TR",
    )
    v1 = (
        _contrast(contrast_ids[0], effect=0.20, ci_low=0.05, ci_high=0.30, blocks=(0.1, 0.3, 0.2)),
        _contrast(contrast_ids[1], effect=0.20, ci_low=0.10, ci_high=0.30, blocks=(0.1, 0.2, 0.3), decision="confirmed"),
        _contrast(contrast_ids[2], effect=0.00, ci_low=-0.05, ci_high=0.05, blocks=(0.0, 0.0, 0.0), track="procurement"),
        _contrast(contrast_ids[3], effect=0.00, ci_low=-0.05, ci_high=0.05, blocks=(0.0, 0.0, 0.0), track="procurement"),
        _contrast(contrast_ids[4], effect=-0.10, ci_low=-0.20, ci_high=-0.02, blocks=(-0.2, -0.1, 0.0), track="trading"),
        _contrast(contrast_ids[5], effect=0.10, ci_low=0.00, ci_high=0.20, blocks=(0.0, 0.1, 0.2), track="trading"),
    )
    v2 = (
        _contrast(contrast_ids[0], effect=0.10, ci_low=0.00, ci_high=0.20, blocks=(0.0, 0.2)),
        _contrast(contrast_ids[1], effect=-0.10, ci_low=-0.20, ci_high=-0.05, blocks=(-0.2, 0.0)),
        _contrast(contrast_ids[2], effect=0.00, ci_low=0.00, ci_high=0.00, blocks=(0.0, 0.0), track="procurement"),
        _contrast(contrast_ids[3], effect=0.20, ci_low=0.10, ci_high=0.30, blocks=(0.1, 0.3), track="procurement"),
        _contrast(contrast_ids[4], effect=-0.20, ci_low=-0.30, ci_high=-0.10, blocks=(-0.1, -0.3), track="trading"),
        _contrast(contrast_ids[5], effect=0.00, ci_low=0.00, ci_high=0.00, blocks=(0.0, 0.0), track="trading"),
    )

    report = analyze_replication_wave(v1, v2, minimum_v2_blocks=2)
    rows = {row.contrast_id: row for row in report.comparisons}

    assert report.errors == ()
    assert tuple(rows) == contrast_ids
    assert rows[contrast_ids[0]].direction_category == "same_sign"
    assert rows[contrast_ids[0]].interval_relation == "overlap"
    assert rows[contrast_ids[1]].direction_category == "sign_disagreement"
    assert rows[contrast_ids[1]].interval_relation == "disjoint"
    assert rows[contrast_ids[2]].direction_category == "both_zero"
    assert rows[contrast_ids[3]].direction_category == "emergent_nonzero"
    assert rows[contrast_ids[4]].direction_category == "same_sign"
    assert rows[contrast_ids[5]].direction_category == "attenuated_to_zero"
    assert {row.wave for row in report.block_effects} == {"v1", "v2"}
    assert len(report.block_effects) == 30
    assert all(row.v1_effect is not None and row.v2_effect is not None for row in rows.values())


def test_replication_analysis_fails_when_v2_has_fewer_than_two_blocks() -> None:
    v1 = (_contrast("only", effect=0.1, ci_low=0.0, ci_high=0.2, blocks=(0.0, 0.1, 0.2)),)
    v2 = (_contrast("only", effect=0.1, ci_low=0.1, ci_high=0.1, blocks=(0.1,)),)

    report = analyze_replication_wave(v1, v2, minimum_v2_blocks=2)

    assert report.errors == ("insufficient_v2_blocks:only:1<2",)
    assert report.comparisons[0].replication_verdict == "not_auditable"
