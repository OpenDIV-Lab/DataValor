"""Block-level, claim-aligned analysis for frozen confirmation studies."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, replace
from typing import Iterable, Mapping

import numpy as np
from scipy.spatial.distance import jensenshannon
from scipy.stats import binomtest, wasserstein_distance

from .metrics import MetricValue
from .models import BenchmarkResult
from .statistics import holm_adjust


@dataclass(frozen=True)
class ContrastSpec:
    contrast_id: str
    track: str
    method_a: str
    method_b: str
    metric: str
    direction: str
    estimand: str
    inference_unit: str
    ci_method: str
    multiplicity_family: str

    def __post_init__(self) -> None:
        if self.direction not in {"higher", "lower", "two_sided"}:
            raise ValueError(f"unsupported direction: {self.direction}")
        if self.inference_unit != "independent_block":
            raise ValueError("confirmatory inference_unit must be independent_block")
        if self.ci_method != "percentile_block_bootstrap":
            raise ValueError("unsupported confirmatory confidence method")


@dataclass(frozen=True)
class ContrastResult:
    contrast_id: str
    track: str
    independent_blocks: int
    case_count: int
    run_count: int
    effect: float | None
    median_effect: float | None
    ci_low: float | None
    ci_high: float | None
    sign_consistency: float | None
    raw_p_value: float | None
    holm_adjusted_p_value: float | None
    worst_block: str | None
    worst_block_effect: float | None
    decision: str
    missing_blocks: tuple[str, ...]
    block_effects: Mapping[str, float]


def _metric_value(row: BenchmarkResult, metric: str) -> float | None:
    raw = row.metrics.get(metric)
    if isinstance(raw, MetricValue):
        if not raw.applicable or raw.value is None:
            return None
        raw = raw.value
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if np.isfinite(value) else None


def _bootstrap_interval(
    effects: np.ndarray,
    *,
    samples: int,
    seed: int,
) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(effects), size=(samples, len(effects)))
    estimates = np.mean(effects[indices], axis=1)
    low, high = np.quantile(estimates, (0.025, 0.975))
    return float(low), float(high)


def _raw_sign_p_value(effects: np.ndarray) -> float:
    nonzero = effects[effects != 0]
    if not len(nonzero):
        return 1.0
    positives = int(np.sum(nonzero > 0))
    return float(binomtest(positives, len(nonzero), 0.5).pvalue)


def _single_contrast(
    rows: tuple[BenchmarkResult, ...],
    spec: ContrastSpec,
    *,
    bootstrap_samples: int,
) -> ContrastResult:
    relevant = tuple(
        row for row in rows
        if row.track == spec.track
        and row.status == "completed"
        and row.method_id in {spec.method_a, spec.method_b}
    )
    blocks_by_case: dict[str, str] = {}
    values: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in relevant:
        block = str(row.metadata.get("independent_block", "")).strip()
        if not block:
            continue
        blocks_by_case[row.case_id] = block
        value = _metric_value(row, spec.metric)
        if value is not None:
            values[(row.case_id, row.method_id)].append(value)
    cases_by_block: dict[str, set[str]] = defaultdict(set)
    for case_id, block in blocks_by_case.items():
        cases_by_block[block].add(case_id)
    missing: list[str] = []
    block_effects: dict[str, float] = {}
    orientation = -1.0 if spec.direction == "lower" else 1.0
    for block, cases in sorted(cases_by_block.items()):
        case_effects: list[float] = []
        for case_id in sorted(cases):
            left = values.get((case_id, spec.method_a), [])
            right = values.get((case_id, spec.method_b), [])
            if not left or not right:
                continue
            case_effects.append(
                orientation * (float(np.mean(left)) - float(np.mean(right)))
            )
        if len(case_effects) != len(cases):
            missing.append(block)
        elif case_effects:
            block_effects[block] = float(np.mean(case_effects))
    case_count = len(blocks_by_case)
    run_count = sum(
        _metric_value(row, spec.metric) is not None for row in relevant
    )
    if missing or not block_effects:
        return ContrastResult(
            spec.contrast_id, spec.track, len(block_effects), case_count, run_count,
            None, None, None, None, None, None, None, None, None,
            "not_auditable", tuple(sorted(missing)), block_effects,
        )
    ordered_blocks = tuple(sorted(block_effects))
    effects = np.asarray([block_effects[block] for block in ordered_blocks])
    seed = int.from_bytes(
        hashlib.sha256(spec.contrast_id.encode("utf-8")).digest()[:8], "big"
    )
    ci_low, ci_high = _bootstrap_interval(
        effects, samples=bootstrap_samples, seed=seed
    )
    if spec.direction == "two_sided":
        decision = "confirmed" if ci_low > 0 or ci_high < 0 else "boundary"
        worst_index = int(np.argmin(np.abs(effects)))
    else:
        decision = (
            "confirmed" if ci_low > 0 else
            "discrepant" if ci_high < 0 else
            "boundary"
        )
        worst_index = int(np.argmin(effects))
    return ContrastResult(
        contrast_id=spec.contrast_id,
        track=spec.track,
        independent_blocks=len(effects),
        case_count=case_count,
        run_count=run_count,
        effect=float(np.mean(effects)),
        median_effect=float(np.median(effects)),
        ci_low=ci_low,
        ci_high=ci_high,
        sign_consistency=float(np.mean(effects > 0)),
        raw_p_value=_raw_sign_p_value(effects),
        holm_adjusted_p_value=None,
        worst_block=ordered_blocks[worst_index],
        worst_block_effect=float(effects[worst_index]),
        decision=decision,
        missing_blocks=(),
        block_effects=block_effects,
    )


def analyze_confirmatory_contrasts(
    results: Iterable[BenchmarkResult],
    specs: Iterable[ContrastSpec],
    *,
    bootstrap_samples: int = 10_000,
) -> tuple[ContrastResult, ...]:
    """Aggregate seeds and cases before treating source blocks as samples."""

    if bootstrap_samples < 100:
        raise ValueError("at least 100 bootstrap samples are required")
    rows = tuple(results)
    specifications = tuple(specs)
    preliminary = [
        _single_contrast(rows, spec, bootstrap_samples=bootstrap_samples)
        for spec in specifications
    ]
    family_indices: dict[str, list[int]] = defaultdict(list)
    for index, (spec, result) in enumerate(zip(specifications, preliminary, strict=True)):
        if result.raw_p_value is not None:
            family_indices[spec.multiplicity_family].append(index)
    for indices in family_indices.values():
        adjusted = holm_adjust([
            float(preliminary[index].raw_p_value) for index in indices
        ])
        for index, value in zip(indices, adjusted, strict=True):
            preliminary[index] = replace(
                preliminary[index], holm_adjusted_p_value=float(value)
            )
    return tuple(preliminary)


def quantify_representativeness(
    development: Iterable[float],
    heldout: Iterable[float],
    *,
    bins: int = 10,
) -> dict[str, float]:
    """Report distinct distribution and support diagnostics, never a composite."""

    raw_heldout = np.asarray(tuple(heldout), dtype=float)
    development_values = np.asarray(tuple(development), dtype=float)
    development_values = development_values[np.isfinite(development_values)]
    heldout_values = raw_heldout[np.isfinite(raw_heldout)]
    if not len(development_values) or not len(heldout_values):
        raise ValueError("representativeness requires finite development and held-out values")
    lower = min(float(np.min(development_values)), float(np.min(heldout_values)))
    upper = max(float(np.max(development_values)), float(np.max(heldout_values)))
    if lower == upper:
        edges = np.linspace(lower - 0.5, upper + 0.5, bins + 1)
    else:
        edges = np.linspace(lower, upper, bins + 1)
    development_hist, _ = np.histogram(development_values, bins=edges)
    heldout_hist, _ = np.histogram(heldout_values, bins=edges)
    development_distribution = (development_hist + 1e-12) / np.sum(development_hist + 1e-12)
    heldout_distribution = (heldout_hist + 1e-12) / np.sum(heldout_hist + 1e-12)
    outside = np.mean(
        (heldout_values < np.min(development_values))
        | (heldout_values > np.max(development_values))
    )
    return {
        "wasserstein_distance": float(
            wasserstein_distance(development_values, heldout_values)
        ),
        "jensen_shannon_divergence": float(
            jensenshannon(development_distribution, heldout_distribution) ** 2
        ),
        "heldout_outside_development_fraction": float(outside),
        "source_coverage": float(len(heldout_values) / len(raw_heldout)),
    }


__all__ = [
    "ContrastResult",
    "ContrastSpec",
    "analyze_confirmatory_contrasts",
    "quantify_representativeness",
]
