from __future__ import annotations

from pathlib import Path

import pytest
from datamechbench.models import MethodSpec
from datamechbench.provenance import (
    coverage_by_kind,
    load_provenance,
    validate_provenance,
)
from datamechbench.registry import MethodRegistry


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _catalog(tmp_path: Path, mechanism_body: str, reference_body: str):
    mechanisms = _write(
        tmp_path / "mechanisms.yaml",
        "schema_version: '2.0'\nmechanisms:\n" + mechanism_body,
    )
    references = _write(
        tmp_path / "references.yaml",
        "schema_version: '1.0'\nreferences:\n" + reference_body,
    )
    return load_provenance(mechanisms, references)


def test_load_provenance_resolves_primary_reference(tmp_path: Path) -> None:
    catalog = _catalog(
        tmp_path,
        """  - method_id: paper_method
    family_id: paper_family
    track: valuation
    implementation_kind: native
    provenance_kind: paper_exact
    reference_keys: [paper]
    algorithm_location: Algorithm 1
    supported_case_types: [analytic]
""",
        """  - reference_id: paper
    kind: paper
    title: A paper
    authors: [A. Author]
    year: 2024
    venue: TestConf
    url: https://example.org/paper
""",
    )

    assert catalog.mechanisms["paper_method"].primary_reference.title == "A paper"
    assert catalog.mechanisms["paper_method"].algorithm_location == "Algorithm 1"


def test_load_provenance_rejects_broken_reference_key(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown reference.*missing"):
        _catalog(
            tmp_path,
            """  - method_id: broken
    family_id: broken
    track: valuation
    implementation_kind: native
    provenance_kind: paper_exact
    reference_keys: [missing]
    algorithm_location: Algorithm 1
    supported_case_types: [analytic]
""",
            """  - reference_id: other
    kind: paper
    title: Other
    authors: [A]
    year: 2020
    venue: V
    url: https://example.org/other
""",
        )


def test_common_baseline_requires_independent_usage_evidence(tmp_path: Path) -> None:
    mechanism = """  - method_id: greedy
    family_id: greedy
    track: procurement
    implementation_kind: native
    provenance_kind: common_baseline
    reference_keys: [implementation]
    baseline_usage_reference_keys: [usage]
    algorithm_location: benchmark implementation
    supported_case_types: [analytic]
"""
    references = """  - reference_id: implementation
    kind: project
    title: Local implementation
    authors: [DataMechBench]
    year: 2026
    venue: software
    url: https://example.org/code
  - reference_id: usage
    kind: paper
    title: One paper
    authors: [A]
    year: 2020
    venue: V
    url: https://example.org/usage
"""

    with pytest.raises(ValueError, match="common baseline.*two papers|established benchmark"):
        _catalog(tmp_path, mechanism, references)


def test_established_benchmark_is_sufficient_baseline_evidence(tmp_path: Path) -> None:
    catalog = _catalog(
        tmp_path,
        """  - method_id: random
    family_id: random
    track: valuation
    implementation_kind: native
    provenance_kind: common_baseline
    reference_keys: [impl]
    baseline_usage_reference_keys: [benchmark]
    algorithm_location: benchmark rule
    supported_case_types: [analytic]
""",
        """  - reference_id: impl
    kind: project
    title: Local
    authors: [DataMechBench]
    year: 2026
    venue: software
    url: https://example.org/local
  - reference_id: benchmark
    kind: benchmark
    title: Established benchmark
    authors: [Benchmark Authors]
    year: 2023
    venue: NeurIPS Datasets and Benchmarks
    url: https://example.org/benchmark
""",
    )

    assert catalog.mechanisms["random"].provenance_kind == "common_baseline"


def test_validate_provenance_requires_registry_catalog_parity(tmp_path: Path) -> None:
    catalog = _catalog(
        tmp_path,
        """  - method_id: catalog_only
    family_id: family
    track: valuation
    implementation_kind: native
    provenance_kind: paper_exact
    reference_keys: [paper]
    algorithm_location: Algorithm 1
    supported_case_types: [analytic]
""",
        """  - reference_id: paper
    kind: paper
    title: Paper
    authors: [A]
    year: 2020
    venue: V
    url: https://example.org/paper
""",
    )
    registry = MethodRegistry()
    registry.register(
        MethodSpec("registry_only", "valuation", "method", "test", "1"),
        lambda _: object(),
    )

    with pytest.raises(ValueError, match="registry_only.*catalog_only"):
        validate_provenance(registry, catalog)


def test_coverage_counts_families_once_and_separates_kinds(tmp_path: Path) -> None:
    catalog = _catalog(
        tmp_path,
        """  - method_id: native
    family_id: same
    track: valuation
    implementation_kind: native
    provenance_kind: paper_exact
    reference_keys: [paper]
    algorithm_location: Algorithm 1
    supported_case_types: [analytic]
  - method_id: official
    family_id: same
    track: valuation
    implementation_kind: external_adapter
    provenance_kind: official_adapter
    reference_keys: [paper, repo]
    algorithm_location: package entrypoint
    supported_case_types: [analytic]
""",
        """  - reference_id: paper
    kind: paper
    title: Paper
    authors: [A]
    year: 2020
    venue: V
    url: https://example.org/paper
  - reference_id: repo
    kind: repository
    title: Official repository
    authors: [A]
    year: 2020
    venue: GitHub
    url: https://github.com/example/repo
    version: abc123
    license: MIT
""",
    )

    counts = coverage_by_kind(catalog, "valuation", "analytic")

    assert counts["method_count"] == 2
    assert counts["family_count"] == 1
    assert counts["independent_literature_family_count"] == 1
    assert counts["by_kind"] == {"official_adapter": 1, "paper_exact": 1}


def test_default_catalog_has_corrected_pay_as_bid_source() -> None:
    catalog = load_provenance()
    record = catalog.mechanisms["pay_as_bid_double"]

    assert record.provenance_kind == "common_baseline"
    assert all("S0004370217300735" not in ref.url for ref in record.references)
    assert record.baseline_usage_references
