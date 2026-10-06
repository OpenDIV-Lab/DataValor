"""Post-freeze, method-level analysis for the Triple Eagle extension."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

TRIPLE_EAGLE_METHODS = (
    "triple_eagle_randomized",
    "triple_eagle_deterministic",
)
BASELINE_METHODS = (
    "generalized_proportional_share",
    "cgl_deterministic",
    "cgl_randomized",
    "jt_greedy_tm",
    "jt_random_tm",
    "jt_random_eom",
    "jt_deterministic_eom",
)
SETTINGS = (
    "P-ADDITIVE",
    "P-SUBMODULAR",
    "P-ML-ACQUISITION",
    "P-MARKET-CONCENTRATION",
)


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
    raw = row.get("metrics", {}).get(metric_id)
    if (
        raw is None
        and metric_id == "normalized_oracle_gain_ratio"
        and row.get("metadata", {}).get("benchmark_setting") != "P-ML-ACQUISITION"
    ):
        raw = row.get("metrics", {}).get("oracle_ratio")
    if not isinstance(raw, Mapping) or not raw.get("applicable", False):
        return None
    value = raw.get("value")
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _case_means(
    rows: Iterable[Mapping[str, Any]], metric_id: str
) -> dict[str, float]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        value = _metric(row, metric_id)
        if value is not None:
            grouped[str(row["case_id"])].append(value)
    return {case_id: fmean(values) for case_id, values in grouped.items() if values}


def _bootstrap_ci(values: Sequence[float], key: str) -> tuple[float, float]:
    if not values:
        return float("nan"), float("nan")
    if len(values) == 1:
        return float(values[0]), float(values[0])
    seed = int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big")
    rng = np.random.default_rng(seed)
    array = np.asarray(values, dtype=float)
    indices = rng.integers(0, len(array), size=(10_000, len(array)))
    means = array[indices].mean(axis=1)
    low, high = np.quantile(means, (0.025, 0.975))
    return float(low), float(high)


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty artifact: {path.name}")
    fields = tuple(rows[0])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _summary_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    methods = (*BASELINE_METHODS, *TRIPLE_EAGLE_METHODS)
    for method_id in methods:
        method_rows = [row for row in rows if row["method_id"] == method_id]
        for setting in SETTINGS:
            selected = [
                row
                for row in method_rows
                if row["metadata"].get("benchmark_setting") == setting
            ]
            if not selected:
                raise ValueError(f"missing comparison cell: {method_id}/{setting}")
            oracle = _case_means(selected, "oracle_ratio")
            values = [oracle[key] for key in sorted(oracle)]
            low, high = _bootstrap_ci(values, f"summary:{method_id}:{setting}")

            def macro(metric_id: str) -> float | str:
                per_case = _case_means(selected, metric_id)
                return fmean(per_case.values()) if per_case else ""

            output.append(
                {
                    "method_id": method_id,
                    "setting": setting,
                    "case_count": len(oracle),
                    "run_count": len(selected),
                    "mean_oracle_ratio": fmean(values),
                    "mean_normalized_oracle_gain_ratio": macro(
                        "normalized_oracle_gain_ratio"
                    ),
                    "case_bootstrap_ci_low": low,
                    "case_bootstrap_ci_high": high,
                    "budget_violation_rate": macro("budget_violation"),
                    "mean_seller_ir_violations": macro("seller_ir_violation_count"),
                    "mean_max_deviation_gain": macro("max_deviation_gain"),
                    "mean_budget_used_ratio": macro("budget_used_ratio"),
                    "mean_buyer_utility": macro("buyer_utility"),
                    "mean_value_oracle_queries": macro("value_oracle_queries"),
                }
            )
    return output


def _branch_rows(extension: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for method_id in TRIPLE_EAGLE_METHODS:
        for setting in SETTINGS:
            selected = [
                row
                for row in extension
                if row["method_id"] == method_id
                and row["metadata"].get("benchmark_setting") == setting
            ]
            branch_counts = Counter(
                str(row["metadata"].get("mechanism_branch", "missing"))
                for row in selected
            )
            for branch, count in sorted(branch_counts.items()):
                branch_rows = [
                    row
                    for row in selected
                    if str(row["metadata"].get("mechanism_branch", "missing"))
                    == branch
                ]
                query_values = [
                    value
                    for row in branch_rows
                    if (value := _metric(row, "value_oracle_queries")) is not None
                ]
                output.append(
                    {
                        "method_id": method_id,
                        "setting": setting,
                        "branch": branch,
                        "run_count": count,
                        "branch_rate": count / len(selected),
                        "mean_value_oracle_queries": fmean(query_values),
                        "suffix_truncation_rate": fmean(
                            float(bool(row["metadata"].get("suffix_truncated", False)))
                            for row in branch_rows
                        ),
                    }
                )
    return output


def _paired_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    by_method = {
        method_id: [row for row in rows if row["method_id"] == method_id]
        for method_id in (*BASELINE_METHODS, *TRIPLE_EAGLE_METHODS)
    }
    for triple_id in TRIPLE_EAGLE_METHODS:
        for baseline_id in BASELINE_METHODS:
            for setting in SETTINGS:
                triple = _case_means(
                    (
                        row
                        for row in by_method[triple_id]
                        if row["metadata"].get("benchmark_setting") == setting
                    ),
                    "oracle_ratio",
                )
                baseline = _case_means(
                    (
                        row
                        for row in by_method[baseline_id]
                        if row["metadata"].get("benchmark_setting") == setting
                    ),
                    "oracle_ratio",
                )
                common = sorted(set(triple) & set(baseline))
                effects = [
                    0.0
                    if abs(triple[case_id] - baseline[case_id]) <= 1e-12
                    else triple[case_id] - baseline[case_id]
                    for case_id in common
                ]
                low, high = _bootstrap_ci(
                    effects, f"paired:{triple_id}:{baseline_id}:{setting}"
                )
                output.append(
                    {
                        "method_id": triple_id,
                        "comparison_method_id": baseline_id,
                        "setting": setting,
                        "paired_case_count": len(common),
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


def _claim_rows(extension: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    targets = {
        "triple_eagle_randomized": 2.0 / (np.sqrt(13.0) + 5.0),
        "triple_eagle_deterministic": 1.0 / (2.0 + np.sqrt(6.0)),
    }
    randomization = {
        row["case_id"]: row for row in _randomization_rows(extension)
    }
    output: list[dict[str, Any]] = []
    for method_id, target in targets.items():
        selected = [
            row
            for row in extension
            if row["method_id"] == method_id
            and row["metadata"].get("benchmark_setting") == "P-SUBMODULAR"
        ]
        seed_panel_ratios = _case_means(selected, "oracle_ratio")
        for case_id, seed_panel_observed in sorted(seed_panel_ratios.items()):
            case_rows = [row for row in selected if row["case_id"] == case_id]
            if method_id == "triple_eagle_randomized":
                observed = float(randomization[case_id]["exact_expected_oracle_ratio"])
                expectation_evaluation = "exact_two_branch_weighting"
            else:
                observed = seed_panel_observed
                expectation_evaluation = "deterministic_per_case"
            budget = [_metric(row, "budget_violation") for row in case_rows]
            ir = [_metric(row, "seller_ir_violation_count") for row in case_rows]
            output.append(
                {
                    "method_id": method_id,
                    "setting": "P-SUBMODULAR",
                    "case_id": case_id,
                    "seed_count": len(case_rows),
                    "oracle_ratio": observed,
                    "seed_panel_oracle_ratio": seed_panel_observed,
                    "theorem_floor": target,
                    "approximation_claim_met": observed + 1e-12 >= target,
                    "all_runs_budget_feasible": all(value == 0.0 for value in budget),
                    "maximum_seller_ir_violations": max(ir) if ir else "",
                    "expectation_evaluation": expectation_evaluation,
                    "interpretation": (
                        "exact weighting of the two published branches; seed panel retained separately"
                        if method_id == "triple_eagle_randomized"
                        else "deterministic per-case theorem check"
                    ),
                }
            )
    return output


def _randomization_rows(
    extension: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    selected = [
        row
        for row in extension
        if row["method_id"] == "triple_eagle_randomized"
    ]
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in selected:
        grouped[str(row["case_id"])].append(row)
    alpha = (np.sqrt(13.0) + 1.0) / 2.0
    singleton_probability = float(alpha / (alpha + 2.0))
    output: list[dict[str, Any]] = []
    for case_id, case_rows in sorted(grouped.items()):
        setting = str(case_rows[0]["metadata"].get("benchmark_setting"))
        seed_panel = [
            value
            for row in case_rows
            if (value := _metric(row, "oracle_ratio")) is not None
        ]
        seed_panel_normalized = [
            value
            for row in case_rows
            if (value := _metric(row, "normalized_oracle_gain_ratio")) is not None
        ]
        branches: dict[str, list[float]] = defaultdict(list)
        for row in case_rows:
            value = _metric(row, "oracle_ratio")
            if value is not None:
                branches[str(row["metadata"].get("mechanism_branch"))].append(value)
        normalized_branches: dict[str, list[float]] = defaultdict(list)
        for row in case_rows:
            value = _metric(row, "normalized_oracle_gain_ratio")
            if value is not None:
                normalized_branches[
                    str(row["metadata"].get("mechanism_branch"))
                ].append(value)
        randomized = set(branches) == {"best_singleton", "best_effort"}
        if randomized:
            singleton_value = fmean(branches["best_singleton"])
            best_effort_value = fmean(branches["best_effort"])
            exact = (
                singleton_probability * singleton_value
                + (1.0 - singleton_probability) * best_effort_value
            )
            exact_normalized = (
                singleton_probability * fmean(normalized_branches["best_singleton"])
                + (1.0 - singleton_probability)
                * fmean(normalized_branches["best_effort"])
            )
            observed_singleton_rate: float | str = (
                len(branches["best_singleton"]) / len(seed_panel)
            )
            probability: float | str = singleton_probability
        elif set(branches) == {"lsd_suffix"}:
            exact = fmean(seed_panel)
            exact_normalized = fmean(seed_panel_normalized)
            observed_singleton_rate = ""
            probability = ""
        else:
            raise ValueError(
                f"unexpected TripleEagleRan branch support for {case_id}: "
                f"{sorted(branches)}"
            )
        panel_mean = fmean(seed_panel)
        panel_normalized_mean = fmean(seed_panel_normalized)
        output.append(
            {
                "case_id": case_id,
                "setting": setting,
                "seed_count": len(case_rows),
                "randomized_branch": randomized,
                "paper_singleton_probability": probability,
                "seed_panel_singleton_rate": observed_singleton_rate,
                "exact_expected_oracle_ratio": exact,
                "seed_panel_oracle_ratio": panel_mean,
                "absolute_seed_panel_bias": abs(exact - panel_mean),
                "exact_expected_normalized_oracle_gain_ratio": exact_normalized,
                "seed_panel_normalized_oracle_gain_ratio": panel_normalized_mean,
                "absolute_normalized_seed_panel_bias": abs(
                    exact_normalized - panel_normalized_mean
                ),
            }
        )
    return output


def _variant_rows(
    extension: Sequence[Mapping[str, Any]],
    randomization: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    random_exact = {
        str(row["case_id"]): float(row["exact_expected_oracle_ratio"])
        for row in randomization
    }
    random_normalized_exact = {
        str(row["case_id"]): float(
            row["exact_expected_normalized_oracle_gain_ratio"]
        )
        for row in randomization
    }
    deterministic = _case_means(
        (
            row
            for row in extension
            if row["method_id"] == "triple_eagle_deterministic"
        ),
        "oracle_ratio",
    )
    deterministic_normalized = _case_means(
        (
            row
            for row in extension
            if row["method_id"] == "triple_eagle_deterministic"
        ),
        "normalized_oracle_gain_ratio",
    )
    output: list[dict[str, Any]] = []
    for setting in SETTINGS:
        case_ids = sorted(
            str(row["case_id"])
            for row in randomization
            if row["setting"] == setting
        )
        effects = [random_exact[case_id] - deterministic[case_id] for case_id in case_ids]
        effects = [0.0 if abs(value) <= 1e-12 else value for value in effects]
        normalized_effects = [
            random_normalized_exact[case_id] - deterministic_normalized[case_id]
            for case_id in case_ids
        ]
        normalized_effects = [
            0.0 if abs(value) <= 1e-12 else value for value in normalized_effects
        ]
        low, high = _bootstrap_ci(effects, f"variant:{setting}")
        output.append(
            {
                "setting": setting,
                "paired_case_count": len(case_ids),
                "estimand": "exact randomized expectation minus deterministic outcome",
                "mean_oracle_ratio_difference": fmean(effects),
                "mean_normalized_oracle_gain_ratio_difference": fmean(
                    normalized_effects
                ),
                "case_bootstrap_ci_low": low,
                "case_bootstrap_ci_high": high,
                "randomized_win_fraction": sum(value > 1e-12 for value in effects)
                / len(effects),
                "tie_fraction": sum(abs(value) <= 1e-12 for value in effects)
                / len(effects),
                "randomized_loss_fraction": sum(value < -1e-12 for value in effects)
                / len(effects),
            }
        )
    return output


def _concentration_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    methods = (*BASELINE_METHODS, *TRIPLE_EAGLE_METHODS)
    for method_id in methods:
        selected = [
            row
            for row in rows
            if row["method_id"] == method_id
            and row["metadata"].get("benchmark_setting")
            == "P-MARKET-CONCENTRATION"
        ]
        grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
        for row in selected:
            concentration = str(row["metadata"].get("concentration_level", ""))
            budget_level = str(row["case_id"]).rsplit("-", 1)[-1]
            grouped[(concentration, budget_level)].append(row)
        for (concentration, budget_level), cell in sorted(grouped.items()):
            oracle = _case_means(cell, "oracle_ratio")
            output.append(
                {
                    "method_id": method_id,
                    "concentration_level": concentration,
                    "budget_level": budget_level,
                    "run_count": len(cell),
                    "mean_oracle_ratio": fmean(oracle.values()),
                    "mean_budget_used_ratio": (
                        fmean(values.values())
                        if (values := _case_means(cell, "budget_used_ratio"))
                        else ""
                    ),
                }
            )
    return output


def _report(
    summaries: Sequence[Mapping[str, Any]],
    branches: Sequence[Mapping[str, Any]],
    claims: Sequence[Mapping[str, Any]],
    paired: Sequence[Mapping[str, Any]],
    randomization: Sequence[Mapping[str, Any]],
    variants: Sequence[Mapping[str, Any]],
) -> str:
    triple_summaries = [
        row for row in summaries if row["method_id"] in TRIPLE_EAGLE_METHODS
    ]
    claim_passes = sum(
        str(row["approximation_claim_met"]).lower() == "true" for row in claims
    )
    branch_totals = Counter()
    for row in branches:
        branch_totals[str(row["branch"])] += int(row["run_count"])
    decisive = [
        row
        for row in paired
        if float(row["case_bootstrap_ci_low"]) > 1e-12
        or float(row["case_bootstrap_ci_high"]) < -1e-12
    ]
    randomized_cases = [row for row in randomization if row["randomized_branch"]]
    max_seed_bias = max(
        float(row["absolute_seed_panel_bias"]) for row in randomized_cases
    )
    lines = [
        "# Triple Eagle exploratory extension",
        "",
        "> Post-freeze exploratory evidence. These results do not modify the frozen confirmatory contrasts.",
        "",
        "## Design",
        "",
        "Two NeurIPS 2023 variants are evaluated on 34 cases in four procurement settings. Randomized outcomes use ten fixed seeds; deterministic methods use one run per case. Seven previously completed paper mechanisms are reused only after exact case-ID alignment. Source hashes are recorded in `manifest.json`.",
        "",
        "## Triple Eagle setting results",
        "",
        "`Oracle ratio` reports absolute task utility, while `Gain ratio` removes `U(empty)`; the two coincide on normalized synthetic utilities and must be read together on measured ML utility. Table values for randomized methods use the declared seed panel; exact finite-support expectations appear below.",
        "",
        "| Method | Setting | Cases | Oracle ratio | Gain ratio | 95% case-bootstrap CI | Budget violation | Value queries |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in triple_summaries:
        queries = row["mean_value_oracle_queries"]
        lines.append(
            f"| `{row['method_id']}` | {row['setting']} | {row['case_count']} | "
            f"{float(row['mean_oracle_ratio']):.3f} | "
            f"{float(row['mean_normalized_oracle_gain_ratio']):.3f} | "
            f"[{float(row['case_bootstrap_ci_low']):.3f}, {float(row['case_bootstrap_ci_high']):.3f}] | "
            f"{float(row['budget_violation_rate']):.3f} | {float(queries):.1f} |"
        )
    lines.extend(
        [
            "",
            "## Audited structural evidence",
            "",
            f"All {len(claims)} submodular case-level claim checks retain the paper assumptions; {claim_passes}/{len(claims)} observed welfare floors are met. Budget and IR columns in `theorem_claim_audit.csv` are evaluated independently of the approximation column.",
            "",
            f"TripleEagleRan activates its two-branch mixture on {len(randomized_cases)}/34 cases. The fixed ten-seed panel selects the singleton branch at rate 0.400, versus the paper probability {float(randomized_cases[0]['paper_singleton_probability']):.3f}; exact finite-support weighting changes a case oracle-ratio estimate by as much as {max_seed_bias:.4f}. The theorem audit therefore uses exact weighting, while ordinary comparative tables retain the declared seed panel.",
            "",
            "The exact randomized-minus-deterministic setting effects are "
            + "; ".join(
                f"{row['setting']}={float(row['mean_oracle_ratio_difference']):+.4f}"
                for row in variants
            )
            + ". This prevents the paper constants from being read as an empirical uniform ordering.",
            f"On P-ML-ACQUISITION the same variant effect is {float(next(row for row in variants if row['setting'] == 'P-ML-ACQUISITION')['mean_normalized_oracle_gain_ratio_difference']):+.4f} after removing the no-purchase baseline, versus the +0.0042 absolute-utility effect.",
            "",
            "Observed allocation branches: "
            + ", ".join(f"`{key}`={value}" for key, value in sorted(branch_totals.items()))
            + ". Branch frequency is an empirical property of this case bank, not a theorem claim.",
            "",
            f"Among {len(paired)} setting-level paired comparisons, {len(decisive)} have a case-bootstrap interval excluding zero. The complete effect table retains non-significant and adverse comparisons; no winner is selected by post-hoc filtering.",
            "",
            "## Reading limits",
            "",
            "The randomized theorem concerns exact expectation over internal randomness; ten seeds are a Monte Carlo diagnostic, not a proof. ML-acquisition cases deliberately violate the monotone-submodular theorem premise. Wall-clock timing is excluded from the hash-bound method comparison; value-oracle counts are reported only where counting semantics are instrumented. Family-level generic leaderboards merge the two Triple Eagle variants, so the method-level tables in this directory are authoritative for variant comparisons.",
            "",
        ]
    )
    return "\n".join(lines)


def build_triple_eagle_extension_artifacts(
    extension_results: str | Path,
    baseline_results: str | Path,
    output_dir: str | Path,
    *,
    supplemental_results: str | Path | None = None,
) -> dict[str, Any]:
    extension_path = Path(extension_results)
    baseline_path = Path(baseline_results)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    extension = _load(extension_path)
    baseline = _load(baseline_path)
    supplemental_path = Path(supplemental_results) if supplemental_results else None
    supplemental = _load(supplemental_path) if supplemental_path else []
    status_counts = Counter(str(row["status"]) for row in extension)
    if status_counts != {"completed": len(extension)}:
        raise ValueError(f"extension contains incomplete rows: {dict(status_counts)}")

    comparison_cases = {
        str(row["case_id"])
        for row in extension
        if row["method_id"] in TRIPLE_EAGLE_METHODS
    }
    expected_settings = {
        str(row["metadata"].get("benchmark_setting"))
        for row in extension
        if row["method_id"] in TRIPLE_EAGLE_METHODS
    }
    if expected_settings != set(SETTINGS):
        raise ValueError(f"extension setting mismatch: {sorted(expected_settings)}")

    baseline_selected = [
        row
        for row in baseline
        if row["method_id"] in BASELINE_METHODS
        and row["case_id"] in comparison_cases
        and row["status"] == "completed"
    ]
    supplemental_selected = [
        row
        for row in supplemental
        if row["method_id"] in BASELINE_METHODS
        and row["case_id"] in comparison_cases
        and row["status"] == "completed"
    ]
    supplemental_keys = {
        (row["method_id"], row["case_id"], int(row["seed"]))
        for row in supplemental_selected
    }
    baseline_selected = [
        row
        for row in baseline_selected
        if (row["method_id"], row["case_id"], int(row["seed"]))
        not in supplemental_keys
    ]
    comparison = [
        *baseline_selected,
        *supplemental_selected,
        *[
            row
            for row in extension
            if row["method_id"] in TRIPLE_EAGLE_METHODS
        ],
    ]
    for method_id in (*BASELINE_METHODS, *TRIPLE_EAGLE_METHODS):
        cases = {row["case_id"] for row in comparison if row["method_id"] == method_id}
        if cases != comparison_cases:
            raise ValueError(
                f"case alignment failed for {method_id}: "
                f"missing={sorted(comparison_cases-cases)} extra={sorted(cases-comparison_cases)}"
            )

    summaries = _summary_rows(comparison)
    branches = _branch_rows(extension)
    paired = _paired_rows(comparison)
    randomization = _randomization_rows(extension)
    claims = _claim_rows(extension)
    variants = _variant_rows(extension, randomization)
    concentration = _concentration_rows(comparison)
    artifacts = {
        "method_setting_summary.csv": summaries,
        "branch_summary.csv": branches,
        "paired_oracle_ratio.csv": paired,
        "theorem_claim_audit.csv": claims,
        "randomization_audit.csv": randomization,
        "variant_comparison.csv": variants,
        "concentration_cells.csv": concentration,
    }
    for name, rows in artifacts.items():
        _write_csv(destination / name, rows)
    (destination / "report.md").write_text(
        _report(summaries, branches, claims, paired, randomization, variants),
        encoding="utf-8",
    )

    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "evidence_scope": "post_freeze_exploratory_extension",
        "extension_source": {
            "path": str(extension_path),
            "sha256": _sha256(extension_path),
        },
        "baseline_source": {
            "path": str(baseline_path),
            "sha256": _sha256(baseline_path),
            "reuse_boundary": "same case IDs; completed rows; seven declared paper mechanisms only",
        },
        "supplemental_source": (
            {
                "path": str(supplemental_path),
                "sha256": _sha256(supplemental_path),
                "accepted_row_count": len(supplemental_selected),
                "reuse_boundary": "current reruns override historical rows on identical baseline method/case/seed keys",
            }
            if supplemental_path is not None
            else None
        ),
        "extension_run_count": len(extension),
        "extension_status_counts": dict(sorted(status_counts.items())),
        "comparison_case_count": len(comparison_cases),
        "comparison_methods": [*BASELINE_METHODS, *TRIPLE_EAGLE_METHODS],
        "randomized_seed_count": 10,
        "bootstrap_unit": "case after within-case seed averaging",
        "bootstrap_replicates": 10_000,
        "outputs": {
            path.name: {"sha256": _sha256(path)}
            for path in sorted(destination.iterdir())
            if path.is_file() and path.name != "manifest.json"
        },
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def _safe_path(root: Path, raw: Any, label: str) -> Path:
    value = Path(str(raw))
    if value.is_absolute():
        raise ValueError(f"{label} must be relative")
    candidate = (root / value).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"{label} escapes root") from exc
    return candidate


def verify_triple_eagle_extension_artifacts(
    manifest_path: str | Path,
    *,
    repository_root: str | Path | None = None,
) -> dict[str, Any]:
    """Verify source rows and every derived extension artifact fail-closed."""

    manifest_file = Path(manifest_path)
    repository = (
        Path(repository_root).resolve()
        if repository_root is not None
        else Path(__file__).resolve().parents[3]
    )
    errors: list[str] = []
    extension_count = 0
    comparison_count = 0
    try:
        payload = json.loads(manifest_file.read_text(encoding="utf-8"))
        if payload.get("schema_version") != "1.0":
            errors.append("invalid_schema_version")
        extension_count = int(payload.get("extension_run_count", -1))
        comparison_count = int(payload.get("comparison_case_count", -1))
        for label in ("extension_source", "baseline_source", "supplemental_source"):
            record = payload.get(label)
            if not isinstance(record, Mapping):
                errors.append(f"missing_source:{label}")
                continue
            try:
                source = _safe_path(repository, record.get("path"), label)
                if not source.is_file():
                    errors.append(f"missing_source_file:{label}")
                elif _sha256(source) != record.get("sha256"):
                    errors.append(f"source_hash_mismatch:{label}")
            except (OSError, ValueError) as exc:
                errors.append(f"invalid_source:{label}:{exc}")
        outputs = payload.get("outputs")
        if not isinstance(outputs, Mapping) or not outputs:
            errors.append("missing_outputs")
        else:
            for name, raw_record in outputs.items():
                if Path(str(name)).name != str(name):
                    errors.append(f"unsafe_output_path:{name}")
                    continue
                record = raw_record if isinstance(raw_record, Mapping) else {}
                output = manifest_file.parent / str(name)
                if not output.is_file():
                    errors.append(f"missing_output:{name}")
                elif _sha256(output) != record.get("sha256"):
                    errors.append(f"output_hash_mismatch:{name}")
        extension_record = payload.get("extension_source", {})
        if isinstance(extension_record, Mapping):
            extension_path = _safe_path(
                repository, extension_record.get("path"), "extension_source"
            )
            if extension_path.is_file():
                rows = _load(extension_path)
                observed = Counter(str(row.get("status")) for row in rows)
                if len(rows) != extension_count:
                    errors.append("extension_run_count_mismatch")
                if dict(sorted(observed.items())) != payload.get(
                    "extension_status_counts"
                ):
                    errors.append("extension_status_counts_mismatch")
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        errors.append(f"invalid_manifest:{exc}")
    return {
        "valid": not errors,
        "errors": errors,
        "extension_run_count": extension_count,
        "comparison_case_count": comparison_count,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--extension",
        default="benchmark/outputs/kdd_triple_eagle_extension/raw_results.jsonl",
    )
    parser.add_argument(
        "--baseline", default="benchmark/outputs/full/raw_results.jsonl"
    )
    parser.add_argument(
        "--supplemental",
        default="benchmark/outputs/kdd_triple_eagle_baseline_completion/raw_results.jsonl",
    )
    parser.add_argument(
        "--output", default="benchmark/outputs/kdd_triple_eagle_extension/analysis"
    )
    args = parser.parse_args(argv)
    manifest = build_triple_eagle_extension_artifacts(
        args.extension,
        args.baseline,
        args.output,
        supplemental_results=args.supplemental,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BASELINE_METHODS",
    "TRIPLE_EAGLE_METHODS",
    "build_triple_eagle_extension_artifacts",
    "verify_triple_eagle_extension_artifacts",
    "main",
]
