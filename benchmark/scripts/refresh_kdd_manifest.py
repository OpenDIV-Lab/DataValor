#!/usr/bin/env python3
"""Refresh hashes in the KDD manifest after an explicitly reviewed change.

This command does not create scientific evidence.  It only rebinds existing
files, recalculates result counts/digests, and removes the retired WWW/SCR
paper-study paths listed below.  Verification remains a separate operation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from datamechbench.report import load_jsonl_results
from datamechbench.reproduction import _source_tree_digest, scientific_result_digest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = REPOSITORY_ROOT / "benchmark/reproduction/kdd2027_core_manifest.json"
RETIRED_PREFIXES = (
    "benchmark/evidence/scr_shapley/",
    "benchmark/evidence/www2027_",
    "benchmark/outputs/scr_shapley/",
    "benchmark/scripts/assemble_scr_confirmatory_evidence.py",
)
REQUIRED_ARTIFACTS = {
    "benchmark/catalog/market_evidence_layers.yaml": "market_semantic_protocol",
    "benchmark/scripts/audit_reference_outcomes.py": "reference_outcome_audit_runner",
    "benchmark/scripts/build_market_semantic_alignment.py": "market_semantic_builder",
    "benchmark/scripts/build_qualification_analysis.py": "qualification_analysis_builder",
    "benchmark/outputs/kdd_heldout_confirmatory/reference_outcome_audit.json": "reference_outcome_audit",
    "benchmark/outputs/kdd_heldout_replication_v2/reference_outcome_audit.json": "replication_reference_outcome_audit",
    "benchmark/outputs/full/reference_outcome_audit.json": "full_matrix_reference_outcome_audit",
    "benchmark/outputs/kdd_market_semantics/market_semantic_alignment.json": "market_semantic_alignment",
    "benchmark/outputs/kdd_market_semantics/evidence_layers.csv": "market_semantic_layer_table",
    "benchmark/outputs/kdd_market_semantics/track_claim_support.csv": "market_semantic_track_table",
    "benchmark/outputs/kdd_market_semantics/report.md": "market_semantic_report",
    "benchmark/outputs/kdd_qualification_analysis/summary.json": "qualification_analysis_summary",
    "benchmark/outputs/kdd_qualification_analysis/method_failure_decomposition.csv": "qualification_failure_table",
    "benchmark/outputs/kdd_qualification_analysis/minimum_relaxation_frontier.csv": "qualification_relaxation_frontier",
    "benchmark/outputs/kdd_qualification_analysis/report.md": "qualification_analysis_report",
    "benchmark/outputs/kdd_paper/table_qualification_decomposition.csv": "paper_table",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _result_binding(path: Path, relative: str) -> dict[str, object]:
    results = load_jsonl_results(path)
    return {
        "path": relative,
        "row_count": len(results),
        "scientific_digest": scientific_result_digest(results),
        "sha256": _sha256(path),
        "status_counts": dict(sorted(Counter(row.status for row in results).items())),
        "track_counts": dict(sorted(Counter(row.track for row in results).items())),
    }


def refresh(manifest_path: Path, repository_root: Path) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    retained = []
    removed = []
    for binding in manifest["artifacts"]:
        relative = str(binding["path"])
        path = repository_root / relative
        if not path.is_file():
            if relative.startswith(RETIRED_PREFIXES):
                removed.append(relative)
                continue
            raise FileNotFoundError(f"manifest artifact is missing: {relative}")
        binding["sha256"] = _sha256(path)
        retained.append(binding)

    own_relative = "benchmark/scripts/refresh_kdd_manifest.py"
    if not any(item["path"] == own_relative for item in retained):
        retained.append(
            {
                "path": own_relative,
                "role": "manifest_maintenance_entrypoint",
                "sha256": _sha256(repository_root / own_relative),
            }
        )
    retained_by_path = {str(item["path"]): item for item in retained}
    for relative, role in sorted(REQUIRED_ARTIFACTS.items()):
        path = repository_root / relative
        if not path.is_file():
            raise FileNotFoundError(f"required KDD artifact is missing: {relative}")
        existing = retained_by_path.get(relative)
        if existing is None:
            existing = {"path": relative, "role": role, "sha256": _sha256(path)}
            retained.append(existing)
            retained_by_path[relative] = existing
        else:
            existing["role"] = role
            existing["sha256"] = _sha256(path)
    manifest["artifacts"] = retained
    manifest["scientific_results"] = _result_binding(
        repository_root / manifest["scientific_results"]["path"],
        manifest["scientific_results"]["path"],
    )
    if manifest.get("replication_scientific_results"):
        manifest["replication_scientific_results"] = _result_binding(
            repository_root / manifest["replication_scientific_results"]["path"],
            manifest["replication_scientific_results"]["path"],
        )
    for binding in manifest["source_trees"]:
        digest, count = _source_tree_digest(repository_root / binding["path"])
        binding["sha256"] = digest
        binding["file_count"] = count
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {"removed": removed, "artifact_count": len(retained)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    args = parser.parse_args()
    result = refresh(args.manifest.resolve(), args.repository_root.resolve())
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
