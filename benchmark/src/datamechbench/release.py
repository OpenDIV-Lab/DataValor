"""Auditable release metadata and paper-facing evidence summaries."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import yaml

from .models import BenchmarkResult
from .provenance import load_provenance
from .resources import resource_path
from .runner import build_cases

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
CATALOG_DIR = resource_path("catalog")
DEFAULT_RELEASE = CATALOG_DIR / "benchmark_release.yaml"


def load_release_metadata(path: str | Path = DEFAULT_RELEASE) -> dict[str, str]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    required = (
        "benchmark_name",
        "benchmark_version",
        "result_schema_version",
        "metric_catalog_version",
    )
    missing = [key for key in required if not str(raw.get(key, "")).strip()]
    if missing:
        raise ValueError(f"release catalog missing: {', '.join(missing)}")
    return {key: str(raw[key]) for key in required}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _payload_digest(results: tuple[BenchmarkResult, ...]) -> str:
    digest = hashlib.sha256()
    for result in sorted(results, key=lambda row: (row.run_id, row.method_id, row.case_id, row.seed)):
        encoded = json.dumps(
            result.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        digest.update(encoded)
        digest.update(b"\n")
    return digest.hexdigest()


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"


def _input_entry(path: Path | None) -> dict[str, str | None]:
    if path is None or not path.is_file():
        return {"status": "missing", "sha256": None, "path": None if path is None else str(path)}
    return {"status": "available", "sha256": _sha256(path), "path": str(path)}


def _source_tree_entry(path: Path) -> dict[str, object]:
    files = sorted(path.rglob("*.py"))
    digest = hashlib.sha256()
    for source in files:
        digest.update(str(source.relative_to(path)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(source.read_bytes())
        digest.update(b"\0")
    return {
        "status": "available" if files else "missing",
        "sha256": digest.hexdigest() if files else None,
        "path": str(path),
        "file_count": len(files),
    }


def _write_benchmark_card(
    path: Path,
    release: dict[str, str],
    counts: dict[str, object],
) -> Path:
    path.write_text(
        f"""# DataMechBench Benchmark Card

## Motivation

DataMechBench {release['benchmark_version']} compares data valuation, procurement, and trading mechanisms while keeping performance, mechanism constraints, statistical evidence, assumption transfer, and cross-evidence deep dives separate.

## Intended use

Use the benchmark to compare mechanism families inside a declared setting, inspect observable guardrails, and identify evidence gaps. It is designed for reproducible research and method submission, not automatic deployment decisions.

## Out-of-scope use

Do not compare ranks across incompatible metrics, infer a theorem from sampled strategic deviations, treat missing guardrails as passing, or collapse tracks into an arbitrary global score.

## Objects and data

The release contains {counts['registered_methods']} registered implementations, {counts['registered_families']} mechanism families, and {counts['catalog_cases']} generated or open-dataset-backed cases. Setting cards and method sources identify assumptions and provenance.

## Protocol and metrics

Seeds are averaged within a case and cases receive equal weight. Each setting declares one primary metric and direction. Complete case coverage is required for qualified rank; constraint-qualified rank additionally requires auditable guardrails to pass.

## Statistical treatment

Common-case comparisons report oriented deltas, wins/ties/losses, a deterministic paired-bootstrap 95% interval, and a two-sided Wilcoxon test with Holm correction. Non-significance is not equivalence.

## Limitations and ethics

Cases approximate selected market assumptions and cannot establish universal dominance. Strategic audits sample deviations rather than exhaust report spaces. Dataset licenses, participant welfare, privacy, and domain-specific market regulation remain deployment responsibilities.

## Maintenance, versioning, and submission

The release manifest hashes catalogs, configuration, result payload, and generated artifacts. Submit `submission.yaml` plus `results.jsonl`, then run `datamechbench validate-submission --submission DIR`. Schema-affecting changes require a release-version update.

## Citation

Until a benchmark paper is published, cite the DataValor repository, the version in `benchmark_manifest.json`, and every evaluated method's primary source from `method_sources.csv`.
""",
        encoding="utf-8",
    )
    return path


def _write_evidence_overview(
    path: Path,
    results: tuple[BenchmarkResult, ...],
    counts: dict[str, object],
) -> Path:
    status = counts["statuses"]
    path.write_text(
        f"""# Benchmark Evidence Index

## Benchmark contributions supported by artifacts

1. Claim- and constraint-aware profiles: `constraint_leaderboard.csv` and `mechanism_profiles.csv`.
2. Common-case statistical comparisons: `pairwise_comparisons.csv` and `statistical_summary.md`.
3. Named assumption-relaxation diagnostics: `assumption_transfer.csv`.
4. Auditable provenance and release inputs: `method_sources.csv` and `benchmark_manifest.json`.
5. Cross-evidence research findings: `deep_dive_report.md` and the four `deep_dive_*.csv` tables.

## Exact experiment inventory

- Result rows: {len(results)}
- Completed: {status.get('completed', 0)}
- Skipped: {status.get('skipped', 0)}
- Failed: {status.get('failed', 0)}
- Observed method IDs: {counts['observed_methods']}
- Observed families: {counts['observed_families']}
- Observed settings: {counts['observed_settings']}
- Observed cases: {counts['observed_cases']}

## Valid claims

- Within-setting performance and coverage claims using the declared primary metric.
- Observable constraint claims for rows marked `pass` or `fail`.
- Paired difference claims only when the corrected decision rule is satisfied.
- Descriptive transfer claims for the named source/target assumptions.
- Deep-dive findings when stated with their recorded competing explanations and validity boundaries.

## Invalid claims

- A universal best mechanism or cross-track total score.
- Equivalence inferred from a non-significant test.
- Formal truthfulness inferred from sampled deviation gain alone.
- Constraint satisfaction inferred from `not_auditable`.
- Treating discovery cards as independent confirmed findings or ignoring a claim's aggregation scale.

## Limitations and next analyses

Use source CSVs for tables and recomputation. Report deferred methods, optional-dependency skips, fidelity labels, dataset representativeness, and sensitivity to case cohorts. Suitable follow-ups include held-out cases and independent reimplementations; these are not claimed by this release.
""",
        encoding="utf-8",
    )
    return path


def write_release_artifacts(
    results: Iterable[BenchmarkResult],
    output_dir: str | Path,
    *,
    config_path: str | Path | None = None,
) -> tuple[Path, ...]:
    materialized = tuple(results)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    release = load_release_metadata()
    provenance = load_provenance()
    cases = build_cases()
    statuses = Counter(row.status for row in materialized)
    counts: dict[str, object] = {
        "registered_methods": len(provenance.mechanisms),
        "registered_families": len({row.family_id for row in provenance.mechanisms.values()}),
        "catalog_cases": sum(len(rows) for rows in cases.values()),
        "results": len(materialized),
        "statuses": {status: statuses[status] for status in ("completed", "skipped", "failed")},
        "observed_methods": len({row.method_id for row in materialized}),
        "observed_families": len({str(row.metadata.get('method_family', row.method_id)) for row in materialized}),
        "observed_settings": len({str(row.metadata.get('benchmark_setting')) for row in materialized if row.metadata.get('benchmark_setting')}),
        "observed_cases": len({row.case_id for row in materialized}),
    }
    card = _write_benchmark_card(destination / "benchmark_card.md", release, counts)
    evidence = _write_evidence_overview(
        destination / "evidence_overview.md", materialized, counts
    )
    catalog_names = (
        "mechanisms.yaml", "references.yaml", "metrics.yaml", "expectations.yaml",
        "qualification.yaml", "assumption_transfers.yaml", "benchmark_release.yaml",
    )
    inputs = {name.removesuffix(".yaml"): _input_entry(CATALOG_DIR / name) for name in catalog_names}
    inputs["headline_suite"] = _input_entry(CATALOG_DIR / "headline_suite.yaml")
    inputs["case_bank_development_v1"] = _input_entry(
        PACKAGE_ROOT / "evidence" / "case_bank_development_v1.json"
    )
    inputs["benchmark_source"] = _source_tree_entry(PACKAGE_ROOT / "src" / "datamechbench")
    inputs["run_config"] = _input_entry(Path(config_path) if config_path is not None else None)
    inputs["raw_results"] = _input_entry(destination / "raw_results.jsonl")
    inputs["result_payload"] = {"status": "available", "sha256": _payload_digest(materialized), "path": None}
    artifacts = [
        {
            "path": str(path.relative_to(destination)),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in sorted(destination.iterdir())
        if path.is_file() and path.name != "benchmark_manifest.json"
    ]
    manifest = {
        "benchmark": {
            "name": release["benchmark_name"],
            "version": release["benchmark_version"],
            "result_schema_version": release["result_schema_version"],
            "metric_catalog_version": release["metric_catalog_version"],
        },
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "numpy": _package_version("numpy"),
            "scipy": _package_version("scipy"),
            "scikit-learn": _package_version("scikit-learn"),
            "datamechbench": _package_version("datamechbench"),
        },
        "inputs": inputs,
        "counts": counts,
        "artifacts": artifacts,
    }
    manifest_path = destination / "benchmark_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path, card, evidence


__all__ = ["load_release_metadata", "write_release_artifacts"]
