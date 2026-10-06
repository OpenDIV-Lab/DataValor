"""Post-freeze analysis of the ICML 2026 BFM-VM procurement mechanism."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

BFM_VM_COMPARISON_METHODS = (
    "generalized_proportional_share",
    "cgl_deterministic",
    "cgl_randomized",
    "jt_greedy_tm",
    "jt_random_tm",
    "jt_random_eom",
    "jt_deterministic_eom",
    "triple_eagle_randomized",
    "triple_eagle_deterministic",
)
BFM_VM_SETTINGS = (
    "P-ADDITIVE",
    "P-SUBMODULAR",
    "P-ML-ACQUISITION",
    "P-MARKET-CONCENTRATION",
)
_BASELINE_METHODS = BFM_VM_COMPARISON_METHODS[:7]
_TRIPLE_EAGLE_METHODS = BFM_VM_COMPARISON_METHODS[7:]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _metric(row: Mapping[str, Any], metric_id: str) -> float | None:
    metric = row.get("metrics", {}).get(metric_id)
    if not isinstance(metric, Mapping) or not metric.get("applicable", False):
        return None
    value = metric.get("value")
    if value is None:
        return None
    return float(value)


def _case_means(
    rows: Iterable[Mapping[str, Any]], metric_id: str
) -> dict[str, float]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        value = _metric(row, metric_id)
        if value is not None:
            grouped[str(row["case_id"])].append(value)
    return {case_id: fmean(values) for case_id, values in grouped.items()}


def _bootstrap_ci(values: Sequence[float], key: str) -> tuple[float, float]:
    if len(values) == 1:
        return float(values[0]), float(values[0])
    seed = int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big")
    array = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(array), size=(10_000, len(array)))
    means = array[indices].mean(axis=1)
    low, high = np.quantile(means, (0.025, 0.975))
    return float(low), float(high)


def paired_bfm_effect_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    comparison_methods: Sequence[str] = BFM_VM_COMPARISON_METHODS,
    settings: Sequence[str] = BFM_VM_SETTINGS,
) -> list[dict[str, Any]]:
    """Compare BFM-VM after first macro-averaging mechanism seeds per case."""

    output: list[dict[str, Any]] = []
    for setting in settings:
        bfm = _case_means(
            (
                row
                for row in rows
                if row["method_id"] == "bfm_vm"
                and row.get("metadata", {}).get("benchmark_setting") == setting
            ),
            "oracle_ratio",
        )
        if not bfm:
            raise ValueError(f"missing BFM-VM setting: {setting}")
        for method_id in comparison_methods:
            comparison = _case_means(
                (
                    row
                    for row in rows
                    if row["method_id"] == method_id
                    and row.get("metadata", {}).get("benchmark_setting") == setting
                ),
                "oracle_ratio",
            )
            if set(comparison) != set(bfm):
                raise ValueError(
                    f"case alignment failed for {method_id}/{setting}: "
                    f"missing={sorted(set(bfm)-set(comparison))} "
                    f"extra={sorted(set(comparison)-set(bfm))}"
                )
            cases = sorted(bfm)
            effects = [
                0.0
                if abs(bfm[case_id] - comparison[case_id]) <= 1e-12
                else bfm[case_id] - comparison[case_id]
                for case_id in cases
            ]
            low, high = _bootstrap_ci(
                effects, f"bfm-vm:{method_id}:{setting}"
            )
            output.append(
                {
                    "method_id": "bfm_vm",
                    "comparison_method_id": method_id,
                    "setting": setting,
                    "paired_case_count": len(cases),
                    "mean_oracle_ratio_difference": fmean(effects),
                    "case_bootstrap_ci_low": low,
                    "case_bootstrap_ci_high": high,
                    "win_fraction": sum(value > 1e-12 for value in effects)
                    / len(effects),
                    "tie_fraction": sum(abs(value) <= 1e-12 for value in effects)
                    / len(effects),
                    "loss_fraction": sum(value < -1e-12 for value in effects)
                    / len(effects),
                }
            )
    return output


def _summary_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for method_id in ("bfm_vm", *BFM_VM_COMPARISON_METHODS):
        for setting in BFM_VM_SETTINGS:
            selected = [
                row
                for row in rows
                if row["method_id"] == method_id
                and row.get("metadata", {}).get("benchmark_setting") == setting
            ]
            oracle = _case_means(selected, "oracle_ratio")
            if not oracle:
                raise ValueError(f"missing summary cell: {method_id}/{setting}")

            def macro(metric_id: str) -> float | str:
                values = _case_means(selected, metric_id)
                return fmean(values.values()) if values else ""

            output.append(
                {
                    "method_id": method_id,
                    "setting": setting,
                    "case_count": len(oracle),
                    "run_count": len(selected),
                    "mean_oracle_ratio": fmean(oracle.values()),
                    "budget_violation_rate": macro("budget_violation"),
                    "mean_seller_ir_violations": macro(
                        "seller_ir_violation_count"
                    ),
                    "mean_max_deviation_gain": macro("max_deviation_gain"),
                    "mean_value_oracle_queries": macro("value_oracle_queries"),
                }
            )
    return output


def _constraint_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    assumptions = {
        "P-ADDITIVE": "within_declared_utility_class",
        "P-SUBMODULAR": "within_declared_utility_class",
        "P-ML-ACQUISITION": "submodularity_not_established",
        "P-MARKET-CONCENTRATION": "within_declared_utility_class",
    }
    output = []
    for setting in BFM_VM_SETTINGS:
        selected = [
            row
            for row in rows
            if row["method_id"] == "bfm_vm"
            and row.get("metadata", {}).get("benchmark_setting") == setting
        ]

        def macro(metric_id: str) -> float | str:
            values = _case_means(selected, metric_id)
            return fmean(values.values()) if values else ""

        output.append(
            {
                "method_id": "bfm_vm",
                "setting": setting,
                "case_count": len({row["case_id"] for row in selected}),
                "theorem_assumption_scope": assumptions[setting],
                "budget_violation_rate": macro("budget_violation"),
                "mean_seller_ir_violations": macro(
                    "seller_ir_violation_count"
                ),
                "mean_max_deviation_gain": macro("max_deviation_gain"),
                "mean_value_oracle_queries": macro("value_oracle_queries"),
                "allowed_conclusion": "finite_case_empirical_audit_only",
            }
        )
    return output


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty artifact: {path.name}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _report(
    summaries: Sequence[Mapping[str, Any]],
    paired: Sequence[Mapping[str, Any]],
    source_audit: Mapping[str, Any],
) -> str:
    bfm = {row["setting"]: row for row in summaries if row["method_id"] == "bfm_vm"}
    decisive = [
        row
        for row in paired
        if float(row["case_bootstrap_ci_low"]) > 0
        or float(row["case_bootstrap_ci_high"]) < 0
    ]
    lines = [
        "# BFM-VM post-freeze procurement extension",
        "",
        "This development-only extension evaluates the paper Algorithm 2 implementation on the existing 34-case procurement surface. It does not modify the frozen KDD headline or held-out protocols.",
        "",
        "## Result surface",
        "",
        "| Setting | Cases | Mean oracle ratio | Budget violation | Seller IR violations | Max sampled deviation gain |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for setting in BFM_VM_SETTINGS:
        row = bfm[setting]
        lines.append(
            f"| {setting} | {row['case_count']} | {float(row['mean_oracle_ratio']):.4f} | "
            f"{float(row['budget_violation_rate']):.4f} | "
            f"{float(row['mean_seller_ir_violations']):.4f} | "
            f"{float(row['mean_max_deviation_gain']):.4f} |"
        )
    lines.extend(
        [
            "",
            "## Comparison finding",
            "",
            f"The complete table contains {len(paired)} BFM-VM-versus-paper-mechanism setting comparisons; {len(decisive)} case-bootstrap intervals exclude zero. Randomized comparators are first averaged within case, so their ten seeds do not increase the effective sample size.",
            "",
            "BFM-VM is not promoted as a universal winner. The artifact preserves ties, losses, and settings outside the theorem assumptions. In particular, measured ML utility is an assumption-transfer stress because submodularity is not established there.",
            "",
            "## Author-source audit",
            "",
            f"The pinned author repository audit concludes `{source_audit['conclusion']}`. The observed structural discrepancies are: "
            + ", ".join(f"`{item}`" for item in source_audit["observed_discrepancies"])
            + ".",
            "",
            "The repository declares no licence file, so its source is not vendored and the audit is not called an official-code parity result. The benchmark implementation follows the paper pseudocode and records stable tie-breaking and defensive out-of-domain behavior as deviations.",
            "",
            "## Claim boundary",
            "",
            "Zero observed violations on this finite case/report grid do not prove truthfulness, individual rationality, or budget feasibility in all domains. The paper theorem and approximation ratio remain source claims under their stated assumptions.",
            "",
        ]
    )
    return "\n".join(lines)


def build_bfm_vm_extension_artifacts(
    bfm_results: str | Path,
    baseline_results: str | Path,
    triple_eagle_results: str | Path,
    supplemental_results: str | Path,
    source_audit_path: str | Path,
    output_dir: str | Path,
    *,
    repository_root: str | Path,
) -> dict[str, Any]:
    root = Path(repository_root).resolve()
    paths = {
        "bfm_results": Path(bfm_results).resolve(),
        "baseline_results": Path(baseline_results).resolve(),
        "triple_eagle_results": Path(triple_eagle_results).resolve(),
        "supplemental_results": Path(supplemental_results).resolve(),
        "source_audit": Path(source_audit_path).resolve(),
    }
    loaded = {key: _load(path) for key, path in paths.items() if key != "source_audit"}
    source_audit = json.loads(paths["source_audit"].read_text(encoding="utf-8"))
    bfm_rows = [
        row for row in loaded["bfm_results"] if row["method_id"] == "bfm_vm"
    ]
    if Counter(str(row["status"]) for row in bfm_rows) != {"completed": len(bfm_rows)}:
        raise ValueError("BFM-VM extension contains incomplete rows")
    comparison_cases = {str(row["case_id"]) for row in bfm_rows}
    if len(comparison_cases) != 34:
        raise ValueError(f"expected 34 BFM-VM cases, observed {len(comparison_cases)}")

    supplemental = [
        row
        for row in loaded["supplemental_results"]
        if row["method_id"] in _BASELINE_METHODS
        and row["case_id"] in comparison_cases
        and row["status"] == "completed"
    ]
    supplemental_keys = {
        (row["method_id"], row["case_id"], int(row["seed"]))
        for row in supplemental
    }
    baseline = [
        row
        for row in loaded["baseline_results"]
        if row["method_id"] in _BASELINE_METHODS
        and row["case_id"] in comparison_cases
        and row["status"] == "completed"
        and (row["method_id"], row["case_id"], int(row["seed"]))
        not in supplemental_keys
    ]
    triple = [
        row
        for row in loaded["triple_eagle_results"]
        if row["method_id"] in _TRIPLE_EAGLE_METHODS
        and row["case_id"] in comparison_cases
        and row["status"] == "completed"
    ]
    comparison = [*bfm_rows, *baseline, *supplemental, *triple]
    paired = paired_bfm_effect_rows(comparison)
    summaries = _summary_rows(comparison)
    constraints = _constraint_rows(comparison)

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, Sequence[Mapping[str, Any]]] = {
        "method_setting_summary.csv": summaries,
        "bfm_vm_paired_oracle_ratio.csv": paired,
        "bfm_vm_constraint_audit.csv": constraints,
    }
    for name, rows in artifacts.items():
        _write_csv(destination / name, rows)
    (destination / "report.md").write_text(
        _report(summaries, paired, source_audit), encoding="utf-8"
    )

    outputs = {}
    for name in (*artifacts, "report.md"):
        path = destination / name
        outputs[name] = {
            "sha256": _sha256(path),
            **({"row_count": len(artifacts[name])} if name in artifacts else {}),
        }
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "evidence_scope": "post_freeze_exploratory_extension",
        "method_id": "bfm_vm",
        "paper_code_alignment": source_audit["conclusion"],
        "frozen_headline_modified": False,
        "comparison_case_count": len(comparison_cases),
        "comparison_methods": ["bfm_vm", *BFM_VM_COMPARISON_METHODS],
        "settings": list(BFM_VM_SETTINGS),
        "bootstrap_replicates": 10_000,
        "bootstrap_unit": "case after within-case seed averaging",
        "inputs": {
            key: {"path": _relative(path, root), "sha256": _sha256(path)}
            for key, path in paths.items()
        },
        "outputs": outputs,
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def verify_bfm_vm_extension_artifacts(
    manifest_path: str | Path,
    *,
    repository_root: str | Path,
) -> dict[str, Any]:
    errors: list[str] = []
    path = Path(manifest_path)
    root = Path(repository_root).resolve()
    comparison_case_count = 0
    comparison_method_count = 0
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        comparison_case_count = int(manifest.get("comparison_case_count", 0))
        comparison_method_count = len(manifest.get("comparison_methods", ()))
        if manifest.get("schema_version") != "1.0":
            errors.append("unsupported_schema_version")
        if manifest.get("evidence_scope") != "post_freeze_exploratory_extension":
            errors.append("wrong_evidence_scope")
        if manifest.get("frozen_headline_modified") is not False:
            errors.append("frozen_headline_boundary_missing")
        for label, binding in manifest.get("inputs", {}).items():
            source = root / str(binding["path"])
            if not source.is_file():
                errors.append(f"missing_input:{label}")
            elif _sha256(source) != binding.get("sha256"):
                errors.append(f"input_hash_mismatch:{label}")
        for name, binding in manifest.get("outputs", {}).items():
            output = path.parent / name
            if not output.is_file():
                errors.append(f"missing_output:{name}")
            elif _sha256(output) != binding.get("sha256"):
                errors.append(f"output_hash_mismatch:{name}")
    except (OSError, ValueError, TypeError, json.JSONDecodeError, KeyError) as exc:
        errors.append(f"invalid_manifest:{exc}")
    return {
        "valid": not errors,
        "errors": errors,
        "comparison_case_count": comparison_case_count,
        "comparison_method_count": comparison_method_count,
    }


__all__ = [
    "BFM_VM_COMPARISON_METHODS",
    "BFM_VM_SETTINGS",
    "build_bfm_vm_extension_artifacts",
    "paired_bfm_effect_rows",
    "verify_bfm_vm_extension_artifacts",
]
