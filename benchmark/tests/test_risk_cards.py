from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from datamechbench.kdd_readiness import load_kdd_target
from datamechbench.risk_cards import (
    RISK_DIMENSIONS,
    build_mechanism_risk_artifacts,
    load_mechanism_risk_cards,
    verify_mechanism_risk_artifacts,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CATALOG = REPOSITORY_ROOT / "benchmark" / "catalog" / "mechanism_risk_cards.yaml"
TARGET = REPOSITORY_ROOT / "benchmark" / "catalog" / "kdd_submission.yaml"
SCRIPT = REPOSITORY_ROOT / "benchmark" / "scripts" / "build_mechanism_risk_cards.py"


def test_default_risk_cards_cover_every_headline_with_explicit_non_composite_boundaries() -> None:
    target = load_kdd_target(TARGET)
    catalog = load_mechanism_risk_cards(
        CATALOG,
        target=target,
        repository_root=REPOSITORY_ROOT,
    )

    assert catalog.no_cross_method_composite is True
    assert len(catalog.cards) == 17
    assert {card.method_id for card in catalog.cards} == set(target.headline_method_ids)
    assert {track: sum(card.track == track for card in catalog.cards) for track in (
        "valuation",
        "procurement",
        "trading",
    )} == {"valuation": 6, "procurement": 6, "trading": 5}

    for card in catalog.cards:
        assert card.affected_roles
        assert card.potential_beneficiaries
        assert card.potentially_burdened_roles
        assert card.deployment_boundary
        assert card.limitations
        assert {
            "automatic_compensation",
            "automatic_market_access",
        }.issubset(card.prohibited_uses)
        assert set(card.dimensions) == set(RISK_DIMENSIONS)
        assert any(item.status == "not_auditable" for item in card.dimensions.values())
        for dimension in card.dimensions.values():
            if dimension.status == "audited_scope":
                assert dimension.evidence_metric_ids
                assert dimension.evidence_paths
                assert dimension.scope
            else:
                assert dimension.reason


def test_risk_card_loader_rejects_incomplete_coverage_and_unsupported_dimension_semantics(
    tmp_path: Path,
) -> None:
    payload = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    payload["cards"].pop()
    incomplete = tmp_path / "incomplete.yaml"
    incomplete.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="headline coverage mismatch"):
        load_mechanism_risk_cards(
            incomplete,
            target=load_kdd_target(TARGET),
            repository_root=REPOSITORY_ROOT,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda payload: payload["cards"][0].update({"fairness_badge": "gold"}),
            "prohibited composite field",
        ),
        (lambda payload: payload["cards"][0].update({"affected_roles": [7]}), "must contain.*strings"),
        (
            lambda payload: payload["cards"][0]["dimensions"][
                "score_or_allocation_incidence"
            ].update({"evidence_metric_ids": ["invented_risk_metric"]}),
            "unknown metric",
        ),
    ],
)
def test_risk_card_loader_rejects_unrecognized_claims_and_unverifiable_evidence(
    tmp_path: Path,
    mutation,
    message: str,
) -> None:
    payload = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    mutation(payload)
    malformed = tmp_path / "malformed.yaml"
    malformed.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_mechanism_risk_cards(
            malformed,
            target=load_kdd_target(TARGET),
            repository_root=REPOSITORY_ROOT,
        )


def test_risk_card_loader_pins_the_frozen_seventeen_independently_of_target(
    tmp_path: Path,
) -> None:
    target_payload = yaml.safe_load(TARGET.read_text(encoding="utf-8"))
    target_payload["flagships"]["trading"]["method_ids"].pop()
    reduced_target = tmp_path / "reduced_target.yaml"
    reduced_target.write_text(
        yaml.safe_dump(target_payload, sort_keys=False), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="frozen headline suite mismatch"):
        load_mechanism_risk_cards(
            CATALOG,
            target=load_kdd_target(reduced_target),
            repository_root=REPOSITORY_ROOT,
        )

    payload = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    card = payload["cards"][0]
    card["dimensions"]["subgroup_fairness"] = {
        "status": "not_auditable",
        "reason": "",
    }
    malformed = tmp_path / "malformed.yaml"
    malformed.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="not_auditable.*reason"):
        load_mechanism_risk_cards(
            malformed,
            target=load_kdd_target(TARGET),
            repository_root=REPOSITORY_ROOT,
        )


def test_risk_artifacts_are_deterministic_machine_readable_and_tamper_evident(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    manifest = build_mechanism_risk_artifacts(
        CATALOG,
        TARGET,
        first,
        repository_root=REPOSITORY_ROOT,
    )
    build_mechanism_risk_artifacts(
        CATALOG,
        TARGET,
        second,
        repository_root=REPOSITORY_ROOT,
    )

    assert manifest["card_count"] == 17
    assert manifest["dimension_row_count"] == 119
    assert manifest["no_cross_method_composite"] is True
    assert set(manifest["outputs"]) == {
        "mechanism_risk_cards.csv",
        "dimension_audit.csv",
        "summary.json",
        "report.md",
    }
    assert manifest["inputs"]["catalog"]["path"] == (
        "benchmark/catalog/mechanism_risk_cards.yaml"
    )
    assert all(
        (first / name).read_bytes() == (second / name).read_bytes()
        for name in (*manifest["outputs"], "manifest.json")
    )

    with (first / "dimension_audit.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    by_key = {(row["method_id"], row["dimension_id"]): row for row in rows}
    jt_payment = by_key[("jt_random_eom", "payment_incidence")]
    lottery_payment = by_key[("lottery_muda", "payment_incidence")]
    assert jt_payment["evidence_coverage_complete"] == "false"
    assert "12/18" in jt_payment["evidence_coverage"]
    assert "missing_payments=6" in jt_payment["evidence_coverage"]
    assert lottery_payment["evidence_coverage_complete"] == "false"
    assert "3/18" in lottery_payment["evidence_coverage"]
    assert "missing_payments=15" in lottery_payment["evidence_coverage"]

    verified = verify_mechanism_risk_artifacts(
        first / "manifest.json",
        repository_root=REPOSITORY_ROOT,
    )
    assert verified == {
        "valid": True,
        "errors": [],
        "card_count": 17,
        "dimension_row_count": 119,
        "no_cross_method_composite": True,
    }

    with (first / "dimension_audit.csv").open("a", encoding="utf-8") as handle:
        handle.write("tampered\n")
    checked = verify_mechanism_risk_artifacts(
        first / "manifest.json",
        repository_root=REPOSITORY_ROOT,
    )
    assert checked["valid"] is False
    assert "hash_mismatch:dimension_audit.csv" in checked["errors"]


@pytest.mark.parametrize("escaped", ["/etc/passwd", "../../etc/passwd"])
def test_risk_artifact_verifier_rejects_input_paths_outside_repository(
    tmp_path: Path,
    escaped: str,
) -> None:
    output = tmp_path / "risk"
    build_mechanism_risk_artifacts(
        CATALOG,
        TARGET,
        output,
        repository_root=REPOSITORY_ROOT,
    )
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["inputs"]["catalog"]["path"] = escaped
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    checked = verify_mechanism_risk_artifacts(
        manifest_path,
        repository_root=REPOSITORY_ROOT,
    )

    assert checked["valid"] is False
    assert any("invalid_input_path:catalog" in error for error in checked["errors"])


def test_risk_card_cli_builds_and_verifies(tmp_path: Path) -> None:
    output = tmp_path / "risk"
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        [
            str(REPOSITORY_ROOT / "benchmark" / "src"),
            str(REPOSITORY_ROOT / "src"),
        ]
    )
    build = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--build",
            "--catalog",
            str(CATALOG),
            "--target",
            str(TARGET),
            "--output-dir",
            str(output),
            "--repository-root",
            str(REPOSITORY_ROOT),
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stderr
    assert json.loads(build.stdout)["card_count"] == 17

    verify = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--verify",
            "--output-dir",
            str(output),
            "--repository-root",
            str(REPOSITORY_ROOT),
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert verify.returncode == 0, verify.stderr
    assert json.loads(verify.stdout)["valid"] is True
