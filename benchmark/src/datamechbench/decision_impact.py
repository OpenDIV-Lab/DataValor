"""Derived audit of decisions changed by complete benchmark contracts.

The incomplete screens in this module are diagnostic counterfactuals.  They
are not claimed to be literature baselines, and results from unlike layers are
never combined into a score.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = PACKAGE_ROOT.parent
DEFAULT_OUTPUT_DIR = PACKAGE_ROOT / "outputs" / "kdd_decision_impact"
DEFAULT_INPUTS = {
    "confirmatory_contrasts": PACKAGE_ROOT
    / "outputs/kdd_paper/table_confirmatory_contrasts.csv",
    "constraint_profiles": PACKAGE_ROOT
    / "outputs/kdd_paper/table_constraint_profiles.csv",
    "finite_incentives": PACKAGE_ROOT
    / "outputs/kdd_paper/table_finite_incentives.csv",
}

DETAIL_COLUMNS = (
    "layer_id",
    "object_id",
    "track",
    "incomplete_screen_verdict",
    "full_protocol_verdict",
    "optimistic_promotion_prevented",
    "reason",
)
SUMMARY_COLUMNS = (
    "layer_id",
    "unit",
    "denominator",
    "incomplete_screen_admitted",
    "full_protocol_admitted",
    "optimistic_promotions_prevented",
    "zero_witness_methods",
    "counterexample_methods",
    "fixed_seed_panel_methods",
    "source_theorem_claims_established",
    "holm_significant_losses",
    "affected_ids",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repository_relative(path: Path, root: Path, label: str) -> str:
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"{label} must be inside repository root: {path}") from exc
    return relative.as_posix()


def _read_csv(path: Path, required: tuple[str, ...]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [name for name in required if name not in (reader.fieldnames or ())]
        if missing:
            raise ValueError(f"{path.name} missing columns: {','.join(missing)}")
        return list(reader)


def _write_csv(path: Path, columns: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def _finite_number(raw: object, label: str) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid numeric value for {label}: {raw!r}") from exc
    if not math.isfinite(value):
        raise ValueError(f"non-finite numeric value for {label}: {raw!r}")
    return value


def _nonnegative_integer(raw: object, label: str) -> int:
    value = _finite_number(raw, label)
    if value < 0 or value != int(value):
        raise ValueError(f"invalid nonnegative integer for {label}: {raw!r}")
    return int(value)


def _coverage(raw: str, label: str) -> tuple[int, int]:
    parts = str(raw).split("/")
    if len(parts) != 2:
        raise ValueError(f"invalid guardrail coverage for {label}: {raw}")
    try:
        observed, expected = (int(part) for part in parts)
    except ValueError as exc:
        raise ValueError(f"invalid guardrail coverage for {label}: {raw}") from exc
    if expected <= 0 or observed < 0 or observed > expected:
        raise ValueError(f"invalid guardrail coverage for {label}: {raw}")
    return observed, expected


def _bool(raw: object, label: str) -> bool:
    if isinstance(raw, bool):
        return raw
    value = str(raw).strip().lower()
    if value in {"true", "1"}:
        return True
    if value in {"false", "0"}:
        return False
    raise ValueError(f"invalid boolean for {label}: {raw!r}")


def _unique_ids(rows: list[dict[str, str]], field: str, label: str) -> None:
    values = [str(row.get(field, "")).strip() for row in rows]
    if any(not value for value in values):
        raise ValueError(f"empty {field} in {label}")
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        raise ValueError(f"duplicate {field} in {label}: {','.join(duplicates)}")


def _confirmatory_layer(
    path: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows = _read_csv(path, ("track", "contrast_id", "effect", "decision"))
    _unique_ids(rows, "contrast_id", path.name)
    details: list[dict[str, Any]] = []
    shortcut_admitted = 0
    full_admitted = 0
    affected: list[str] = []
    for row in sorted(rows, key=lambda item: item["contrast_id"]):
        effect = _finite_number(row["effect"], f"{row['contrast_id']}.effect")
        decision = row["decision"]
        if decision not in {"confirmed", "boundary", "discrepant"}:
            raise ValueError(f"invalid confirmatory decision {decision!r}")
        shortcut = effect > 0
        full = decision == "confirmed"
        prevented = shortcut and not full
        shortcut_admitted += int(shortcut)
        full_admitted += int(full)
        if prevented:
            affected.append(row["contrast_id"])
        details.append(
            {
                "layer_id": "confirmatory_claims",
                "object_id": row["contrast_id"],
                "track": row["track"],
                "incomplete_screen_verdict": "admit" if shortcut else "do_not_admit",
                "full_protocol_verdict": "admit" if full else decision,
                "optimistic_promotion_prevented": str(prevented).lower(),
                "reason": (
                    "positive_effect_without_complete_confirmation"
                    if prevented
                    else "screen_and_protocol_do_not_create_optimistic_promotion"
                ),
            }
        )
    return (
        {
            "layer_id": "confirmatory_claims",
            "unit": "registered_contrast",
            "denominator": len(rows),
            "incomplete_screen_admitted": shortcut_admitted,
            "full_protocol_admitted": full_admitted,
            "optimistic_promotions_prevented": len(affected),
            "affected_ids": affected,
        },
        details,
    )


def _constraint_layer(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows = _read_csv(
        path,
        (
            "track",
            "method_id",
            "completed_runs",
            "primary_mean",
            "guardrail_1_coverage",
            "guardrail_1_max",
            "guardrail_2_coverage",
            "guardrail_2_max",
        ),
    )
    rows = [row for row in rows if row["track"] in {"procurement", "trading"}]
    _unique_ids(rows, "method_id", path.name)
    details: list[dict[str, Any]] = []
    shortcut_admitted = 0
    full_admitted = 0
    affected: list[str] = []
    for row in sorted(rows, key=lambda item: item["method_id"]):
        completed = _nonnegative_integer(
            row["completed_runs"], f"{row['method_id']}.completed_runs"
        )
        primary = _finite_number(row["primary_mean"], f"{row['method_id']}.primary_mean")
        del primary
        coverages = [
            _coverage(row[f"guardrail_{index}_coverage"], row["method_id"])
            for index in (1, 2)
        ]
        maxima = [
            _finite_number(
                row[f"guardrail_{index}_max"],
                f"{row['method_id']}.guardrail_{index}_max",
            )
            for index in (1, 2)
        ]
        shortcut = completed > 0
        full = shortcut and all(a == b for a, b in coverages) and all(
            value <= 0 for value in maxima
        )
        prevented = shortcut and not full
        shortcut_admitted += int(shortcut)
        full_admitted += int(full)
        if prevented:
            affected.append(row["method_id"])
        details.append(
            {
                "layer_id": "constraint_admissibility",
                "object_id": row["method_id"],
                "track": row["track"],
                "incomplete_screen_verdict": "admit" if shortcut else "do_not_admit",
                "full_protocol_verdict": "admit" if full else "not_auditable_or_failed",
                "optimistic_promotion_prevented": str(prevented).lower(),
                "reason": (
                    "incomplete_or_failed_guardrail"
                    if prevented
                    else "complete_passing_guardrails"
                ),
            }
        )
    return (
        {
            "layer_id": "constraint_admissibility",
            "unit": "procurement_or_trading_headline_method",
            "denominator": len(rows),
            "incomplete_screen_admitted": shortcut_admitted,
            "full_protocol_admitted": full_admitted,
            "optimistic_promotions_prevented": len(affected),
            "affected_ids": affected,
        },
        details,
    )


def _incentive_layer(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows = _read_csv(
        path,
        (
            "track",
            "method_id",
            "profitable_deviation_count",
            "conclusion",
            "report_domain_complete",
            "random_support_complete",
        ),
    )
    _unique_ids(rows, "method_id", path.name)
    details: list[dict[str, Any]] = []
    zero_witness: list[str] = []
    counterexamples: list[str] = []
    fixed_panels: list[str] = []
    for row in sorted(rows, key=lambda item: item["method_id"]):
        count = _nonnegative_integer(
            row["profitable_deviation_count"],
            f"{row['method_id']}.profitable_deviation_count",
        )
        report_complete = _bool(
            row["report_domain_complete"], f"{row['method_id']}.report_domain_complete"
        )
        random_complete = _bool(
            row["random_support_complete"], f"{row['method_id']}.random_support_complete"
        )
        conclusion = row["conclusion"]
        if not report_complete:
            raise ValueError(f"incomplete report domain for {row['method_id']}")
        if count == 0:
            zero_witness.append(row["method_id"])
            full_verdict = (
                "bounded_no_counterexample_complete_finite_domain"
                if random_complete
                else "bounded_no_counterexample_fixed_seed_panel"
            )
        else:
            counterexamples.append(row["method_id"])
            full_verdict = "discrepancy_requires_source_assumption_analysis"
        if not random_complete:
            fixed_panels.append(row["method_id"])
        if count == 0 and not conclusion.startswith("no_counterexample"):
            raise ValueError(f"inconsistent zero-witness conclusion for {row['method_id']}")
        if count > 0 and conclusion != "counterexample_within_audited_domain":
            raise ValueError(f"inconsistent witness conclusion for {row['method_id']}")
        details.append(
            {
                "layer_id": "finite_incentive_claims",
                "object_id": row["method_id"],
                "track": row["track"],
                "incomplete_screen_verdict": (
                    "upgrade_source_claim" if count == 0 else "counterexample"
                ),
                "full_protocol_verdict": full_verdict,
                "optimistic_promotion_prevented": str(count == 0).lower(),
                "reason": (
                    "zero_witnesses_do_not_establish_source_theorem"
                    if count == 0
                    else "witness_does_not_automatically_refute_source_theorem"
                ),
            }
        )
    return (
        {
            "layer_id": "finite_incentive_claims",
            "unit": "audited_mechanism",
            "denominator": len(rows),
            "zero_witness_methods": len(zero_witness),
            "source_theorem_claims_established": 0,
            "counterexample_methods": len(counterexamples),
            "fixed_seed_panel_methods": len(fixed_panels),
            "affected_ids": zero_witness,
        },
        details,
    )


def _json_ready(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


def _report(layers: list[dict[str, Any]]) -> str:
    index = {item["layer_id"]: item for item in layers}
    confirmatory = index["confirmatory_claims"]
    constraints = index["constraint_admissibility"]
    incentives = index["finite_incentive_claims"]
    return "\n".join(
        (
            "# Decision-impact audit",
            "",
            "These deliberately incomplete screens are diagnostic counterfactuals, "
            "not claimed literature baselines. Unlike evidence units are never "
            "combined into a score.",
            "",
            "| Layer | Incomplete screen | Full protocol | Impact |",
            "|---|---:|---:|---|",
            f"| Confirmatory claims | {confirmatory['incomplete_screen_admitted']}/{confirmatory['denominator']} admitted | {confirmatory['full_protocol_admitted']}/{confirmatory['denominator']} confirmed | {confirmatory['optimistic_promotions_prevented']} optimistic promotions prevented |",
            f"| Constraint admissibility | {constraints['incomplete_screen_admitted']}/{constraints['denominator']} admitted | {constraints['full_protocol_admitted']}/{constraints['denominator']} auditable and passing | {constraints['optimistic_promotions_prevented']} incomplete/failed profiles excluded |",
            f"| Finite incentive claims | {incentives['zero_witness_methods']}/{incentives['denominator']} have zero witnesses | {incentives['source_theorem_claims_established']} source theorems established | {incentives['counterexample_methods']} methods retain discrepancy witnesses |",
            "",
            "No cross-layer percentage or overall winner is defined.",
            "",
        )
    )


def build_decision_impact(
    inputs: Mapping[str, str | Path] = DEFAULT_INPUTS,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    *,
    repository_root: str | Path = REPOSITORY_ROOT,
) -> dict[str, Any]:
    """Build deterministic decision-impact artifacts from frozen evidence."""

    required = tuple(DEFAULT_INPUTS)
    if set(inputs) != set(required):
        raise ValueError(f"decision-impact inputs must be exactly: {','.join(required)}")
    paths = {name: Path(inputs[name]).resolve() for name in required}
    root = Path(repository_root).resolve()
    for name, path in paths.items():
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"missing regular decision-impact input {name}: {path}")

    layer_builders = (
        _confirmatory_layer(paths["confirmatory_contrasts"]),
        _constraint_layer(paths["constraint_profiles"]),
        _incentive_layer(paths["finite_incentives"]),
    )
    layers = [summary for summary, _ in layer_builders]
    details = [row for _, rows in layer_builders for row in rows]
    summary = {
        "schema_version": "1.0",
        "study_id": "kdd2027-decision-impact-v1",
        "claim_scope": "diagnostic_counterfactual_decision_impact",
        "no_cross_layer_composite": True,
        "layers": layers,
    }
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    summary_path = output / "summary.json"
    summary_path.write_text(
        json.dumps(_json_ready(summary), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    layer_rows = []
    for layer in layers:
        row = dict(layer)
        row["affected_ids"] = ";".join(layer.get("affected_ids", ()))
        layer_rows.append(row)
    _write_csv(output / "layer_summary.csv", SUMMARY_COLUMNS, layer_rows)
    _write_csv(output / "decision_details.csv", DETAIL_COLUMNS, details)
    (output / "report.md").write_text(_report(layers), encoding="utf-8")
    output_names = (
        "decision_details.csv",
        "layer_summary.csv",
        "report.md",
        "summary.json",
    )
    manifest = {
        "schema_version": "1.0",
        "manifest_kind": "kdd_decision_impact",
        "study_id": summary["study_id"],
        "claim_scope": summary["claim_scope"],
        "no_cross_layer_composite": True,
        "inputs": {
            name: {
                "path": _repository_relative(path, root, f"input {name}"),
                "sha256": _sha256(path),
            }
            for name, path in sorted(paths.items())
        },
        "outputs": {
            name: {
                "sha256": _sha256(output / name),
                "bytes": (output / name).stat().st_size,
            }
            for name in output_names
        },
        "row_counts": {
            "decision_details.csv": len(details),
            "layer_summary.csv": len(layers),
        },
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def verify_decision_impact_manifest(manifest_path: str | Path) -> dict[str, Any]:
    """Verify decision-impact outputs without trusting their manifest hashes."""

    path = Path(manifest_path)
    errors: list[str] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (
            payload.get("schema_version") != "1.0"
            or payload.get("manifest_kind") != "kdd_decision_impact"
            or payload.get("no_cross_layer_composite") is not True
        ):
            errors.append("invalid_manifest_schema")
        outputs = payload.get("outputs")
        if not isinstance(outputs, Mapping):
            raise ValueError("outputs must be an object")
        for name, binding in outputs.items():
            if Path(str(name)).name != name:
                errors.append(f"unsafe_output_path:{name}")
                continue
            if not isinstance(binding, Mapping):
                errors.append(f"invalid_output_binding:{name}")
                continue
            target = path.parent / name
            if not target.is_file() or target.is_symlink():
                errors.append(f"missing_output:{name}")
                continue
            if _sha256(target) != binding.get("sha256"):
                errors.append(f"output_sha256_mismatch:{name}")
            if target.stat().st_size != binding.get("bytes"):
                errors.append(f"output_size_mismatch:{name}")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"invalid_decision_impact_manifest:{exc}")
    return {"valid": not errors, "errors": errors, "manifest": str(path)}


__all__ = [
    "DEFAULT_INPUTS",
    "DEFAULT_OUTPUT_DIR",
    "build_decision_impact",
    "verify_decision_impact_manifest",
]
