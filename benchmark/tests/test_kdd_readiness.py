from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path

import datamechbench.kdd_readiness as kdd_readiness
import pytest
import yaml
from datamechbench.kdd_readiness import (
    PostReleaseEvidenceAudit,
    audit_finite_incentive_evidence,
    audit_kdd_readiness,
    audit_paper_artifact_evidence,
    audit_post_release_evidence,
    audit_public_release_evidence,
    load_kdd_target,
)
from datamechbench.provenance import load_provenance
from datamechbench.report import load_jsonl_results
from datamechbench.reproduction import CleanRoomAudit

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TARGET = REPOSITORY_ROOT / "benchmark" / "catalog" / "kdd_submission.yaml"


def _gate(report, gate_id: str):
    return next(gate for gate in report.gates if gate.gate_id == gate_id)


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _post_release_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    core = tmp_path / "core-manifest.json"
    core.write_text('{"release":"fixture-v1"}\n', encoding="utf-8")
    public = tmp_path / "public-release.yaml"
    public.write_text("release_id: fixture-v1\n", encoding="utf-8")
    operator = tmp_path / "operator-a.json"
    operator.write_text('{"operator":"a"}\n', encoding="utf-8")
    manifest = tmp_path / "post-release.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0",
                "manifest_kind": "kdd_post_release_evidence",
                "release_id": "fixture-v1",
                "core_manifest": {
                    "path": core.name,
                    "sha256": _sha256_path(core),
                },
                "public_release_record": {
                    "path": public.name,
                    "sha256": _sha256_path(public),
                },
                "clean_room_records": [
                    {"path": operator.name, "sha256": _sha256_path(operator)}
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return manifest, core, public, operator


def test_post_release_evidence_missing_is_not_an_error(tmp_path: Path) -> None:
    audit = audit_post_release_evidence(
        tmp_path / "missing.yaml",
        tmp_path,
        expected_release_id="fixture-v1",
        expected_core_manifest_path="core-manifest.json",
    )

    assert audit.present is False
    assert audit.common_errors == ()
    assert audit.public_errors == ()
    assert audit.clean_room_errors == ()
    assert audit.public_release_record is None
    assert audit.clean_room_records == ()


def test_post_release_evidence_binds_immutable_core_and_external_records(
    tmp_path: Path,
) -> None:
    manifest, _, public, operator = _post_release_fixture(tmp_path)

    audit = audit_post_release_evidence(
        manifest,
        tmp_path,
        expected_release_id="fixture-v1",
        expected_core_manifest_path="core-manifest.json",
    )

    assert audit.present is True
    assert audit.common_errors == ()
    assert audit.public_errors == ()
    assert audit.clean_room_errors == ()
    assert audit.public_release_record == public.name
    assert audit.clean_room_records == (operator.name,)


@pytest.mark.parametrize(
    ("mutation", "error_scope", "expected_error"),
    [
        ("schema", "common", "unsupported_schema_version"),
        ("release", "common", "release_id_mismatch"),
        ("core_path", "common", "core_manifest_path_mismatch"),
        ("core_hash", "common", "core_manifest_hash_mismatch"),
        ("public_hash", "public", "hash_mismatch:public-release.yaml"),
        ("operator_hash", "clean", "hash_mismatch:operator-a.json"),
        ("duplicate_operator", "clean", "duplicate_path:operator-a.json"),
        ("duplicate_public", "clean", "duplicate_path:public-release.yaml"),
        ("escaping_operator", "clean", "path_escapes_repository_root"),
        ("noncanonical_operator", "clean", "noncanonical_path"),
    ],
)
def test_post_release_evidence_fails_closed_by_evidence_scope(
    tmp_path: Path, mutation: str, error_scope: str, expected_error: str
) -> None:
    manifest, _, _, _ = _post_release_fixture(tmp_path)
    payload = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    if mutation == "schema":
        payload["schema_version"] = "0"
    elif mutation == "release":
        payload["release_id"] = "other-release"
    elif mutation == "core_path":
        payload["core_manifest"]["path"] = "other-core.json"
    elif mutation == "core_hash":
        payload["core_manifest"]["sha256"] = "0" * 64
    elif mutation == "public_hash":
        payload["public_release_record"]["sha256"] = "0" * 64
    elif mutation == "operator_hash":
        payload["clean_room_records"][0]["sha256"] = "0" * 64
    elif mutation == "duplicate_operator":
        payload["clean_room_records"].append(
            dict(payload["clean_room_records"][0])
        )
    elif mutation == "duplicate_public":
        payload["clean_room_records"][0] = dict(payload["public_release_record"])
    elif mutation == "escaping_operator":
        payload["clean_room_records"][0]["path"] = "../operator-a.json"
    elif mutation == "noncanonical_operator":
        payload["clean_room_records"][0]["path"] = "./operator-a.json"
    manifest.write_text(
        yaml.safe_dump(payload, sort_keys=False), encoding="utf-8"
    )

    audit = audit_post_release_evidence(
        manifest,
        tmp_path,
        expected_release_id="fixture-v1",
        expected_core_manifest_path="core-manifest.json",
    )
    errors = {
        "common": audit.common_errors,
        "public": audit.public_errors,
        "clean": audit.clean_room_errors,
    }[error_scope]

    assert any(expected_error in error for error in errors)


def test_post_release_evidence_rejects_symlinked_binding(tmp_path: Path) -> None:
    manifest, _, _, operator = _post_release_fixture(tmp_path)
    actual = tmp_path / "operator-real.json"
    operator.rename(actual)
    operator.symlink_to(actual.name)

    audit = audit_post_release_evidence(
        manifest,
        tmp_path,
        expected_release_id="fixture-v1",
        expected_core_manifest_path="core-manifest.json",
    )

    assert any(
        error == "missing_or_unsafe_file:operator-a.json"
        for error in audit.clean_room_errors
    )


def test_post_release_evidence_rejects_symlinked_manifest(tmp_path: Path) -> None:
    manifest, _, _, _ = _post_release_fixture(tmp_path)
    actual = tmp_path / "post-release-real.yaml"
    manifest.rename(actual)
    manifest.symlink_to(actual.name)

    audit = audit_post_release_evidence(
        manifest,
        tmp_path,
        expected_release_id="fixture-v1",
        expected_core_manifest_path="core-manifest.json",
    )

    assert audit.present is True
    assert audit.common_errors == ("unsafe_post_release_manifest",)


def _target_with_heldout(tmp_path: Path, manifests: list[Path]) -> Path:
    payload = yaml.safe_load(DEFAULT_TARGET.read_text(encoding="utf-8"))
    payload["evidence"]["heldout_manifests"] = [str(path) for path in manifests]
    target_path = tmp_path / "target.yaml"
    target_path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return target_path


def test_default_kdd_target_freezes_three_tracks_and_seventeen_families() -> None:
    target = load_kdd_target(DEFAULT_TARGET, provenance=load_provenance())

    assert target.venue == "KDD 2027"
    assert target.track == "Datasets & Benchmarks"
    assert set(target.flagships) == {"valuation", "procurement", "trading"}
    assert {item.setting_id for item in target.flagships.values()} == {
        "V-REPLICATION-ROBUSTNESS",
        "P-MARKET-CONCENTRATION",
        "T-MARKET-THICKNESS",
    }
    assert len(target.headline_family_ids) == 17
    assert len(target.flagships["valuation"].method_ids) == 6
    assert len(target.flagships["procurement"].method_ids) == 6
    assert len(target.flagships["trading"].method_ids) == 5
    assert "random_sampling_double" not in target.headline_family_ids
    assert target.artifact_manifest == "benchmark/reproduction/kdd2027_core_manifest.json"
    assert target.finite_incentive_manifest == (
        "benchmark/evidence/kdd_finite_incentive_audit_v1.json"
    )
    assert target.paper_artifact_manifest == (
        "benchmark/outputs/kdd_paper/paper_artifact_manifest.json"
    )
    assert target.market_semantic_alignment == (
        "benchmark/outputs/kdd_market_semantics/market_semantic_alignment.json"
    )
    assert target.qualification_analysis == (
        "benchmark/outputs/kdd_qualification_analysis/summary.json"
    )
    assert target.replication_report_manifest == (
        "benchmark/outputs/kdd_heldout_replication_v2/replication_manifest.json"
    )
    assert target.public_release_record == (
        "benchmark/catalog/kdd_public_release.yaml"
    )
    assert target.mechanism_risk_manifest == (
        "benchmark/outputs/kdd_mechanism_risks/manifest.json"
    )
    assert target.clean_room_operators_min == 2
    assert target.clean_room_records == ()
    assert target.post_release_evidence_manifest == (
        "benchmark/evidence/post_release/kdd_release_evidence.yaml"
    )
    assert target.external_validation_records_min == 5
    assert target.external_validation_fixtures_min == 3
    assert target.external_validation_methods_min == 5
    assert target.external_validation_sources_min == 4
    assert target.external_validation_repositories_min == 3
    assert target.external_validation_tracks_min == 2
    assert target.external_validation_records == (
        "benchmark/evidence/external_opendataval_knn_shapley_v1.json",
        "benchmark/evidence/external_erelsgl_mcafee_v1.json",
        "benchmark/evidence/external_erelsgl_trade_reduction_v1.json",
        "benchmark/evidence/external_erelsgl_sbba_v1.json",
        "benchmark/evidence/external_svarm_exact_shapley_v1.json",
    )


def test_target_rejects_unknown_headline_method(tmp_path: Path) -> None:
    target = tmp_path / "target.yaml"
    target.write_text(DEFAULT_TARGET.read_text(encoding="utf-8").replace(
        "shapley_exact", "not_a_registered_method", 1
    ), encoding="utf-8")

    with pytest.raises(ValueError, match="unknown headline method.*not_a_registered_method"):
        load_kdd_target(target, provenance=load_provenance())


def test_reference_core_spans_two_primary_sources_per_track() -> None:
    provenance = load_provenance()
    target = load_kdd_target(DEFAULT_TARGET, provenance=provenance)

    report = audit_kdd_readiness(
        (), target, provenance=provenance, repository_root=REPOSITORY_ROOT
    )

    gate = _gate(report, "reference_source_diversity")
    assert gate.status == "pass"
    assert gate.evidence["valuation"]["source_count"] >= 2
    assert gate.evidence["procurement"]["source_ids"] == [
        "cgl_budget_feasible",
        "jalaly_tardos",
    ]
    assert gate.evidence["trading"]["source_ids"] == [
        "mcafee_double_auction",
        "sbba",
    ]


def test_current_release_audit_fails_closed_on_unmet_kdd_evidence() -> None:
    target = load_kdd_target(DEFAULT_TARGET, provenance=load_provenance())
    results = load_jsonl_results(
        REPOSITORY_ROOT / "benchmark" / "outputs" / "full" / "raw_results.jsonl"
    )

    report = audit_kdd_readiness(
        results,
        target,
        provenance=load_provenance(),
        repository_root=REPOSITORY_ROOT,
    )

    assert report.ready is False
    assert _gate(report, "wheel_installability_contract").status == "pass"
    assert _gate(report, "trusted_metric_recomputation").status == "pass"
    assert _gate(report, "reference_outcome_recomputation").status in {
        "pass",
        "not_evidenced",
    }
    assert _gate(report, "kdd_release_scope_isolation").status == "pass"
    assert _gate(report, "headline_family_count").status == "pass"
    assert _gate(report, "completed_flagship_coverage").status == "pass"
    assert _gate(report, "no_failed_runs").status == "pass"
    reference_gate = _gate(report, "reference_grade_per_track")
    assert reference_gate.status == "pass"
    assert reference_gate.evidence["valuation"] >= 2
    assert reference_gate.evidence["procurement"] == 5
    assert reference_gate.evidence["trading"] == 3
    alignment_gate = _gate(report, "result_provenance_alignment")
    assert alignment_gate.status == "pass"
    assert alignment_gate.evidence["mismatches"] == []
    parity_gate = _gate(report, "parity_evidence")
    assert parity_gate.status == "pass"
    assert parity_gate.evidence["verified_count"] == 17
    assert parity_gate.evidence["unverified"] == {}
    independent = _gate(report, "independent_case_blocks")
    assert independent.status == "pass"
    assert independent.evidence["blocks"] == {
        "valuation": 7,
        "procurement": 4,
        "trading": 4,
    }
    assert independent.evidence["generator_families"] == {
        "valuation": 3,
        "procurement": 4,
        "trading": 4,
    }
    assert independent.evidence["cohorts"] == {
        "valuation": ["development"],
        "procurement": ["development"],
        "trading": ["development"],
    }
    assert independent.next_action == (
        "Preserve the frozen development bank and add only newly frozen held-out blocks."
    )
    assert independent.evidence["errors"] == []
    heldout = _gate(report, "real_heldout_evidence")
    assert heldout.status == "pass"
    assert heldout.evidence["blocks"] == {
        "valuation": 5,
        "procurement": 5,
        "trading": 5,
    }
    assert heldout.evidence["economic_semantics"] == {
        "valuation": {
            "task_utility": 5,
            "proxy": 0,
            "listing_ask": 0,
            "settlement": 0,
            "elicited_reservation": 0,
        },
        "procurement": {
            "task_utility": 0,
            "proxy": 5,
            "listing_ask": 0,
            "settlement": 0,
            "elicited_reservation": 0,
        },
        "trading": {
            "task_utility": 0,
            "proxy": 5,
            "listing_ask": 0,
            "settlement": 0,
            "elicited_reservation": 0,
        },
    }
    assert heldout.evidence["economic_claim_support"] == {
        "task_utility": 5,
        "proxy_calibration": 10,
        "listing_ask": 0,
        "transaction_price": 0,
        "reservation_value": 0,
        "buyer_value": 0,
    }
    assert heldout.evidence["unique_source_uris"] == {
        "valuation": 5,
        "procurement": 2,
        "trading": 2,
    }
    assert heldout.evidence["licenses"] == {
        "CC-BY-4.0": 1,
        "CC0-1.0": 6,
        "Elexon-BMRS-Open-Data-Licence": 5,
        "UCI-CC-BY-4.0": 3,
    }
    assert heldout.evidence["errors"] == []
    semantic = _gate(report, "market_semantic_alignment")
    assert semantic.status == "pass"
    assert semantic.evidence["layer_count"] == 6
    assert semantic.evidence["supported_tracks"] == [
        "procurement",
        "trading",
        "valuation",
    ]
    assert semantic.evidence["private_type_observed_layer_count"] == 0
    assert semantic.evidence["mechanism_outcome_replayable_layer_count"] == 0
    qualification = _gate(report, "qualification_failure_decomposition")
    assert qualification.status == "pass"
    assert qualification.evidence["headline_method_count"] == 5
    assert qualification.evidence["joint_pass_count"] == 0
    assert qualification.evidence["one_requirement_near_miss_count"] == 3
    assert qualification.evidence["minimum_relaxation_path_count"] == 4
    replication = _gate(report, "independent_replication_wave")
    assert replication.status == "pass"
    assert replication.evidence["blocks"] == {
        "valuation": 2,
        "procurement": 2,
        "trading": 2,
    }
    assert replication.evidence["contrast_count"] == 6
    assert replication.evidence["v2_confirmed_count"] == 0
    assert replication.evidence["v2_boundary_count"] == 6
    assert replication.evidence["pooled_inference"] is False
    assert replication.evidence["errors"] == []
    artifact = _gate(report, "artifact_reproduction_contract")
    assert artifact.status == "pass"
    assert artifact.evidence["verified_artifacts"] >= 240
    assert artifact.evidence["row_count"] == 210
    assert artifact.evidence["scientific_digest"] == (
        "40d0110e66c80ce2bf4ac763be71f4260ac1f55ce4ce04b389843757041dd781"
    )
    incentives = _gate(report, "finite_domain_incentive_audit")
    assert incentives.status == "pass"
    assert incentives.evidence["covered_method_count"] == 11
    assert incentives.evidence["counterexample_methods"] == ["lottery_muda", "sbba"]
    assert incentives.evidence["errors"] == []
    paper = _gate(report, "paper_artifact_contract")
    assert paper.status == "pass"
    assert paper.evidence["output_count"] == 13
    assert paper.evidence["row_counts"] == {
        "table_confirmatory_contrasts.csv": 6,
        "table_constraint_profiles.csv": 17,
        "table_finite_incentives.csv": 11,
        "table_replication_wave.csv": 6,
        "table_economic_observable_scope.csv": 4,
        "table_qualification_decomposition.csv": 5,
        "table_scope_fidelity.csv": 17,
    }
    assert paper.evidence["errors"] == []
    risk_cards = _gate(report, "mechanism_risk_cards")
    assert risk_cards.status == "pass"
    assert risk_cards.evidence == {
        "valid": True,
        "errors": [],
        "card_count": 17,
        "dimension_row_count": 119,
        "no_cross_method_composite": True,
    }
    public_release = _gate(report, "public_release_artifact")
    assert public_release.status == "not_evidenced"
    assert public_release.evidence["candidate_valid"] is True
    assert public_release.evidence["missing_external_fields"] == [
        "archive_doi",
        "archive_url",
        "citation.creators",
        "citation.publication_date",
        "public_repository_url",
    ]
    assert public_release.evidence["errors"] == []
    clean_room = _gate(report, "clean_room_reproduction")
    assert clean_room.status == "not_evidenced"
    assert clean_room.evidence["required_operators"] == 2
    assert clean_room.evidence["observed_operators"] == 0
    external = _gate(report, "external_implementation_validation")
    assert external.status == "pass"
    assert external.evidence["record_count"] == 5
    assert external.evidence["distinct_record_count"] == 5
    assert external.evidence["distinct_method_count"] == 5
    assert external.evidence["track_count"] == 2
    assert external.evidence["validated_method_ids"] == [
        "knn_shapley",
        "mcafee",
        "sbba",
        "shapley_exact",
        "trade_reduction",
    ]
    assert external.evidence["official_upstream_count"] == 4
    assert external.evidence["unique_external_source_count"] == 4
    assert external.evidence["unique_external_repository_count"] == 3
    assert external.evidence["fixture_count"] == 21
    assert external.evidence["maximum_absolute_error"] <= 1e-7
    assert external.evidence["errors"] == []


def test_readiness_fails_closed_when_mechanism_risk_artifact_is_tampered(
    tmp_path: Path,
) -> None:
    source = REPOSITORY_ROOT / "benchmark" / "outputs" / "kdd_mechanism_risks"
    destination = tmp_path / "risks"
    shutil.copytree(source, destination)
    with (destination / "dimension_audit.csv").open("a", encoding="utf-8") as handle:
        handle.write("tampered\n")
    target = replace(
        load_kdd_target(DEFAULT_TARGET, provenance=load_provenance()),
        mechanism_risk_manifest=str(destination / "manifest.json"),
    )

    report = audit_kdd_readiness(
        (),
        target,
        provenance=load_provenance(),
        repository_root=REPOSITORY_ROOT,
    )

    gate = _gate(report, "mechanism_risk_cards")
    assert gate.status == "fail"
    assert "hash_mismatch:dimension_audit.csv" in gate.evidence["errors"]


def _published_policy(source: Path, destination: Path) -> dict:
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    payload["publication"].update({
        "public_repository_url": "https://github.com/example/datamechbench",
        "archive_url": "https://doi.org/10.5281/zenodo.1234567",
        "archive_doi": "10.5281/zenodo.1234567",
    })
    payload["citation"].update({
        "creators": [{"name": "Test Researcher"}],
        "publication_date": "2026-10-04",
    })
    destination.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return payload


def _candidate_archive_sha256() -> str:
    policy = yaml.safe_load(
        (
            REPOSITORY_ROOT
            / "benchmark"
            / "catalog"
            / "kdd_public_release.yaml"
        ).read_text(encoding="utf-8")
    )
    sidecar = json.loads(
        (REPOSITORY_ROOT / policy["candidate"]["manifest"]).read_text(
            encoding="utf-8"
        )
    )
    return str(sidecar["archive"]["sha256"])


def test_public_release_audit_passes_only_with_valid_external_identifiers(
    tmp_path: Path,
) -> None:
    source = REPOSITORY_ROOT / "benchmark" / "catalog" / "kdd_public_release.yaml"
    policy = tmp_path / "published.yaml"
    _published_policy(source, policy)

    audit = audit_public_release_evidence(
        policy,
        REPOSITORY_ROOT,
        expected_release_id="datamechbench-reference-v0.3-code",
    )

    assert audit["status"] == "pass"
    assert audit["candidate_valid"] is True
    assert audit["missing_external_fields"] == []
    assert audit["artifact_license"] == "Apache-2.0"
    assert audit["license_file"] == "LICENSE"
    assert audit["license_sha256"] == hashlib.sha256(
        (REPOSITORY_ROOT / "LICENSE").read_bytes()
    ).hexdigest()
    assert audit["archive_url"] == "https://doi.org/10.5281/zenodo.1234567"
    assert audit["archive_sha256"] == _candidate_archive_sha256()
    assert audit["errors"] == []


def test_public_release_audit_keeps_missing_citation_identity_not_evidenced(
    tmp_path: Path,
) -> None:
    source = REPOSITORY_ROOT / "benchmark" / "catalog" / "kdd_public_release.yaml"
    policy = tmp_path / "unpublished.yaml"
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    payload["publication"].update({
        "public_repository_url": "https://github.com/example/datamechbench",
        "archive_url": "https://doi.org/10.5281/zenodo.1234567",
        "archive_doi": "10.5281/zenodo.1234567",
    })
    policy.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    audit = audit_public_release_evidence(
        policy,
        REPOSITORY_ROOT,
        expected_release_id="datamechbench-reference-v0.3-code",
    )

    assert audit["status"] == "not_evidenced"
    assert audit["missing_external_fields"] == [
        "citation.creators",
        "citation.publication_date",
    ]
    assert audit["errors"] == []


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        (
            lambda payload: payload["citation"].update(
                {"creators": [{"name": "<insert author>"}]}
            ),
            "placeholder_citation_creator:0",
        ),
        (
            lambda payload: payload["citation"].update({"version": "wrong-version"}),
            "citation_version_mismatch:expected=datamechbench-reference-v0.3-code:observed=wrong-version",
        ),
        (
            lambda payload: payload["citation"].update({"license": "MIT"}),
            "citation_license_mismatch:expected=Apache-2.0:observed=MIT",
        ),
        (
            lambda payload: payload["citation"].update(
                {"publication_date": "October 4, 2026"}
            ),
            "malformed_citation_publication_date",
        ),
    ],
)
def test_public_release_audit_rejects_invalid_citation_metadata(
    tmp_path: Path, mutation, expected_error: str
) -> None:
    source = REPOSITORY_ROOT / "benchmark" / "catalog" / "kdd_public_release.yaml"
    policy = tmp_path / "invalid-citation.yaml"
    payload = _published_policy(source, policy)
    mutation(payload)
    policy.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    audit = audit_public_release_evidence(
        policy,
        REPOSITORY_ROOT,
        expected_release_id="datamechbench-reference-v0.3-code",
    )

    assert audit["status"] == "fail"
    assert expected_error in audit["errors"]


def test_readiness_binds_clean_room_records_to_published_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = REPOSITORY_ROOT / "benchmark" / "catalog" / "kdd_public_release.yaml"
    policy = tmp_path / "published.yaml"
    _published_policy(source, policy)
    target = replace(
        load_kdd_target(DEFAULT_TARGET, provenance=load_provenance()),
        post_release_evidence_manifest=str(tmp_path / "post-release.yaml"),
    )
    observed: dict[str, object] = {}

    def fake_clean_room_audit(
        paths,
        repository_root,
        expected_manifest_path,
        *,
        required_operators,
        expected_archive_url,
        expected_archive_sha256,
    ):
        observed.update(
            {
                "paths": paths,
                "repository_root": repository_root,
                "expected_manifest_path": expected_manifest_path,
                "required_operators": required_operators,
                "expected_archive_url": expected_archive_url,
                "expected_archive_sha256": expected_archive_sha256,
            }
        )
        return CleanRoomAudit(
            passed=True,
            errors=(),
            valid_records=2,
            operator_ids=("operator-a", "operator-b"),
            covered_tracks=("procurement", "trading", "valuation"),
            required_operators=2,
        )

    monkeypatch.setattr(
        kdd_readiness, "audit_clean_room_records", fake_clean_room_audit
    )
    monkeypatch.setattr(
        kdd_readiness,
        "audit_post_release_evidence",
        lambda *args, **kwargs: PostReleaseEvidenceAudit(
            manifest=str(tmp_path / "post-release.yaml"),
            present=True,
            release_id="datamechbench-reference-v0.3-code",
            core_manifest_sha256="a" * 64,
            public_release_record=str(policy),
            clean_room_records=("benchmark/evidence/operator-a.json",),
            common_errors=(),
            public_errors=(),
            clean_room_errors=(),
        ),
    )

    report = audit_kdd_readiness(
        (), target, provenance=load_provenance(), repository_root=REPOSITORY_ROOT
    )

    assert observed["expected_archive_url"] == (
        "https://doi.org/10.5281/zenodo.1234567"
    )
    assert observed["expected_archive_sha256"] == _candidate_archive_sha256()
    assert _gate(report, "clean_room_reproduction").status == "pass"


def test_invalid_post_release_core_binding_fails_both_external_gates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = replace(
        load_kdd_target(DEFAULT_TARGET, provenance=load_provenance()),
        post_release_evidence_manifest=str(tmp_path / "post-release.yaml"),
    )
    monkeypatch.setattr(
        kdd_readiness,
        "audit_post_release_evidence",
        lambda *args, **kwargs: PostReleaseEvidenceAudit(
            manifest=str(tmp_path / "post-release.yaml"),
            present=True,
            release_id="datamechbench-reference-v0.3-code",
            core_manifest_sha256="0" * 64,
            public_release_record=None,
            clean_room_records=(),
            common_errors=("core_manifest_hash_mismatch",),
            public_errors=(),
            clean_room_errors=(),
        ),
    )

    report = audit_kdd_readiness(
        (), target, provenance=load_provenance(), repository_root=REPOSITORY_ROOT
    )

    public_gate = _gate(report, "public_release_artifact")
    clean_gate = _gate(report, "clean_room_reproduction")
    assert public_gate.status == "fail"
    assert clean_gate.status == "fail"
    assert "post_release:core_manifest_hash_mismatch" in public_gate.evidence["errors"]
    assert "post_release:core_manifest_hash_mismatch" in clean_gate.evidence["errors"]


def test_public_release_audit_rejects_incorrect_artifact_license(
    tmp_path: Path,
) -> None:
    source = REPOSITORY_ROOT / "benchmark" / "catalog" / "kdd_public_release.yaml"
    policy = tmp_path / "wrong-license.yaml"
    payload = _published_policy(source, policy)
    payload["artifact_license"] = "MIT"
    policy.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    audit = audit_public_release_evidence(
        policy,
        REPOSITORY_ROOT,
        expected_release_id="datamechbench-reference-v0.3-code",
    )

    assert audit["status"] == "fail"
    assert (
        "artifact_license_mismatch:expected=Apache-2.0:observed=MIT"
        in audit["errors"]
    )


def test_public_release_audit_rejects_unbound_license_bytes(tmp_path: Path) -> None:
    source = REPOSITORY_ROOT / "benchmark" / "catalog" / "kdd_public_release.yaml"
    policy = tmp_path / "wrong-license-hash.yaml"
    payload = _published_policy(source, policy)
    payload["license_file"]["sha256"] = "0" * 64
    policy.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    audit = audit_public_release_evidence(
        policy,
        REPOSITORY_ROOT,
        expected_release_id="datamechbench-reference-v0.3-code",
    )

    assert audit["status"] == "fail"
    assert "license_sha256_mismatch:LICENSE" in audit["errors"]


def test_public_release_audit_rejects_malformed_doi(tmp_path: Path) -> None:
    source = REPOSITORY_ROOT / "benchmark" / "catalog" / "kdd_public_release.yaml"
    policy = tmp_path / "malformed.yaml"
    payload = _published_policy(source, policy)
    payload["publication"]["archive_doi"] = "not-a-doi"
    policy.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    audit = audit_public_release_evidence(
        policy,
        REPOSITORY_ROOT,
        expected_release_id="datamechbench-reference-v0.3-code",
    )

    assert audit["status"] == "fail"
    assert "malformed_archive_doi" in audit["errors"]


def test_public_release_audit_rejects_tampered_candidate(tmp_path: Path) -> None:
    source_policy = REPOSITORY_ROOT / "benchmark" / "catalog" / "kdd_public_release.yaml"
    payload = yaml.safe_load(source_policy.read_text(encoding="utf-8"))
    source_sidecar = REPOSITORY_ROOT / payload["candidate"]["manifest"]
    source_manifest = json.loads(source_sidecar.read_text(encoding="utf-8"))
    source_archive = source_sidecar.parent / source_manifest["archive"]["path"]
    archive = tmp_path / source_archive.name
    sidecar = tmp_path / source_sidecar.name
    shutil.copy2(source_archive, archive)
    shutil.copy2(source_sidecar, sidecar)
    archive.write_bytes(archive.read_bytes() + b"tamper")
    payload["candidate"] = {
        "archive": str(archive),
        "manifest": str(sidecar),
    }
    policy = tmp_path / "tampered.yaml"
    policy.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    audit = audit_public_release_evidence(
        policy,
        REPOSITORY_ROOT,
        expected_release_id="datamechbench-reference-v0.3-code",
    )

    assert audit["status"] == "fail"
    assert audit["candidate_valid"] is False
    assert any("archive_sha256_mismatch" in error for error in audit["errors"])


def test_final_headline_target_has_no_parity_gaps() -> None:
    target = load_kdd_target(DEFAULT_TARGET, provenance=load_provenance())

    verified = {
        method_id
        for method_id, evidence in target.parity_evidence.items()
        if evidence.status == "verified"
    }
    unverified = {
        method_id: evidence.status
        for method_id, evidence in target.parity_evidence.items()
        if evidence.status != "verified"
    }

    assert len(verified) == 17
    assert unverified == {}


def test_finite_incentive_gate_rejects_theorem_language_and_random_overclaim(
    tmp_path: Path,
) -> None:
    source_evidence = REPOSITORY_ROOT / "benchmark" / "evidence" / "kdd_finite_incentive_audit_v1.json"
    source_output = REPOSITORY_ROOT / "benchmark" / "outputs" / "kdd_finite_incentives"
    evidence_dir = tmp_path / "evidence"
    output_dir = tmp_path / "outputs" / "kdd_finite_incentives"
    evidence_dir.mkdir(parents=True)
    shutil.copytree(source_output, output_dir)
    manifest_path = evidence_dir / "audit.json"
    manifest = json.loads(source_evidence.read_text(encoding="utf-8"))
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    result_path = output_dir / "audit_results.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    stochastic = next(record for record in result["methods"] if record["stochastic"])
    stochastic["conclusion"] = "truthful proof"
    stochastic["random_support_complete"] = True
    result_path.write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
    manifest["artifacts"][0]["sha256"] = hashlib.sha256(result_path.read_bytes()).hexdigest()
    manifest["artifacts"][0]["bytes"] = result_path.stat().st_size
    manifest["scientific_digest"] = manifest["artifacts"][0]["sha256"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    target = load_kdd_target(DEFAULT_TARGET, provenance=load_provenance())
    expected = {
        method_id
        for track in ("procurement", "trading")
        for method_id in target.flagships[track].method_ids
    }

    audit = audit_finite_incentive_evidence(manifest_path, expected)

    assert audit["passed"] is False
    assert any("prohibited_conclusion_language" in error for error in audit["errors"])
    assert any("random_support_overclaim" in error for error in audit["errors"])


def test_paper_artifact_gate_rejects_missing_svg_accessibility_label(
    tmp_path: Path,
) -> None:
    source = REPOSITORY_ROOT / "benchmark" / "outputs" / "kdd_paper"
    copied = tmp_path / "kdd_paper"
    shutil.copytree(source, copied)
    svg = copied / "figure_trading_thickness.svg"
    svg.write_text(svg.read_text(encoding="utf-8").replace("<title>", "<not-title>").replace("</title>", "</not-title>"), encoding="utf-8")
    manifest_path = copied / "paper_artifact_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["outputs"][svg.name]["sha256"] = hashlib.sha256(svg.read_bytes()).hexdigest()
    manifest["outputs"][svg.name]["bytes"] = svg.stat().st_size
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    target = load_kdd_target(DEFAULT_TARGET, provenance=load_provenance())

    audit = audit_paper_artifact_evidence(
        manifest_path, set(target.headline_method_ids)
    )

    assert audit["passed"] is False
    assert any("missing_svg_title:figure_trading_thickness.svg" in error for error in audit["errors"])


def test_paper_artifact_gate_recomputes_table_row_counts(tmp_path: Path) -> None:
    source = REPOSITORY_ROOT / "benchmark" / "outputs" / "kdd_paper"
    copied = tmp_path / "kdd_paper"
    shutil.copytree(source, copied)
    table = copied / "table_constraint_profiles.csv"
    lines = table.read_text(encoding="utf-8").splitlines()
    table.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    manifest_path = copied / "paper_artifact_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["outputs"][table.name]["sha256"] = hashlib.sha256(table.read_bytes()).hexdigest()
    manifest["outputs"][table.name]["bytes"] = table.stat().st_size
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    target = load_kdd_target(DEFAULT_TARGET, provenance=load_provenance())

    audit = audit_paper_artifact_evidence(
        manifest_path, set(target.headline_method_ids)
    )

    assert audit["passed"] is False
    assert any(
        "actual_row_count:table_constraint_profiles.csv:expected=17:observed=16"
        in error
        for error in audit["errors"]
    )


def test_stale_result_fidelity_is_rejected() -> None:
    target = load_kdd_target(DEFAULT_TARGET, provenance=load_provenance())
    results = load_jsonl_results(
        REPOSITORY_ROOT / "benchmark" / "outputs" / "full" / "raw_results.jsonl"
    )
    source = next(
        row
        for row in results
        if row.method_id == "mcafee"
        and row.status == "completed"
        and row.metadata.get("benchmark_setting") == "T-MARKET-THICKNESS"
    )
    stale = replace(
        source,
        metadata={**source.metadata, "provenance_kind": "paper_variant"},
    )

    report = audit_kdd_readiness(
        (stale,),
        target,
        provenance=load_provenance(),
        repository_root=REPOSITORY_ROOT,
    )

    gate = _gate(report, "result_provenance_alignment")
    assert gate.status == "fail"
    assert gate.evidence["mismatches"] == [{
        "track": "trading",
        "method_id": "mcafee",
        "expected": "paper_exact",
        "observed": ["paper_variant"],
    }]


def test_controlled_fixture_cannot_satisfy_real_heldout_gate(tmp_path: Path) -> None:
    manifest = tmp_path / "controlled.json"
    manifest.write_text(json.dumps({
        "cohort": "heldout",
        "evidence_scope": "controlled_cached_game",
        "tracks": ["valuation", "procurement", "trading"],
    }), encoding="utf-8")
    target_path = _target_with_heldout(tmp_path, [manifest])
    target = load_kdd_target(target_path, provenance=load_provenance())

    report = audit_kdd_readiness(
        (), target, provenance=load_provenance(), repository_root=REPOSITORY_ROOT
    )

    gate = _gate(report, "real_heldout_evidence")
    assert gate.status == "fail"


def test_legacy_self_reported_track_list_cannot_satisfy_real_heldout_gate(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "legacy.json"
    manifest.write_text(json.dumps({
        "cohort": "heldout",
        "evidence_scope": "real_trained_game",
        "tracks": ["valuation", "procurement", "trading"],
    }), encoding="utf-8")
    target_path = _target_with_heldout(tmp_path, [manifest])
    target = load_kdd_target(target_path, provenance=load_provenance())

    report = audit_kdd_readiness(
        (), target, provenance=load_provenance(), repository_root=REPOSITORY_ROOT
    )

    gate = _gate(report, "real_heldout_evidence")
    assert gate.status == "fail"
    assert any("manifest_kind" in error for error in gate.evidence["errors"])


def test_real_heldout_manifest_requires_all_flagship_tracks(tmp_path: Path) -> None:
    manifest = tmp_path / "real.json"
    manifest.write_text(json.dumps({
        "cohort": "heldout",
        "evidence_scope": "real_trained_game",
        "tracks": ["valuation"],
    }), encoding="utf-8")
    target_path = _target_with_heldout(tmp_path, [manifest])
    target = load_kdd_target(target_path, provenance=load_provenance())

    report = audit_kdd_readiness(
        (), target, provenance=load_provenance(), repository_root=REPOSITORY_ROOT
    )

    gate = _gate(report, "real_heldout_evidence")
    assert gate.status == "fail"
    assert gate.evidence["missing_tracks"] == ["procurement", "trading", "valuation"]
    assert any("manifest_kind" in error for error in gate.evidence["errors"])


def test_independent_case_gate_derives_counts_from_explicit_completed_blocks(
    tmp_path: Path,
) -> None:
    results_path = REPOSITORY_ROOT / "benchmark" / "outputs" / "full" / "raw_results.jsonl"
    results = load_jsonl_results(results_path)
    selections = {
        "valuation": (
            ("VREP-breast_cancer-c1", "V-REPLICATION-ROBUSTNESS", "replication"),
            ("VAX-additive", "V-AXIOM", "axiom"),
            ("VCORR-breast_cancer-label-20", "V-CORRUPTION", "corruption"),
        ),
        "procurement": (
            ("PCONC-diffuse-b2", "P-MARKET-CONCENTRATION", "concentration"),
            ("PADD-independent-b30", "P-ADDITIVE", "additive"),
            ("PSMOD-coverage-b30", "P-SUBMODULAR", "coverage"),
        ),
        "trading": (
            ("TTHICK-n2-k1", "T-MARKET-THICKNESS", "thickness"),
            ("TDOUBLE-n2-low", "T-DOUBLE", "independent"),
            ("TCORR-n2", "T-CORRELATED", "correlated"),
        ),
    }
    manifest = tmp_path / "case-bank.json"
    manifest.write_text(json.dumps({
        "schema_version": "1.0",
        "manifest_kind": "independent_case_bank",
        "results": {
            "path": str(results_path),
            "sha256": hashlib.sha256(results_path.read_bytes()).hexdigest(),
        },
        "tracks": {
            track: {"blocks": [{
                "block_id": f"{track}-{family}",
                "cohort": "development",
                "setting_id": setting,
                "generator_family": family,
                "independence_unit": "generator_family",
                "source_kind": "controlled_generator",
                "source_uri": f"benchmark://{family}",
                "license_id": "MIT",
                "input_hash": hashlib.sha256(family.encode()).hexdigest(),
                "case_ids": [case_id],
            } for case_id, setting, family in blocks]}
            for track, blocks in selections.items()
        },
    }), encoding="utf-8")
    target_text = DEFAULT_TARGET.read_text(encoding="utf-8").replace(
        "independent_case_manifests:\n    - benchmark/evidence/case_bank_development_v1.json",
        f"independent_case_manifests:\n    - {manifest}",
    )
    target_path = tmp_path / "target.yaml"
    target_path.write_text(target_text, encoding="utf-8")
    target = load_kdd_target(target_path, provenance=load_provenance())

    report = audit_kdd_readiness(
        results, target, provenance=load_provenance(), repository_root=REPOSITORY_ROOT
    )

    gate = _gate(report, "independent_case_blocks")
    assert gate.status == "pass"
    assert gate.evidence["blocks"] == {track: 3 for track in selections}
    assert gate.evidence["generator_families"] == {track: 3 for track in selections}
    assert gate.evidence["cohorts"] == {track: ["development"] for track in selections}
    assert gate.evidence["errors"] == []
