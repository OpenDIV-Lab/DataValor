"""Versioned metric definitions and conditional paper-claim annotations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from .models import BenchmarkResult
from .resources import resource_path

CATALOG_DIR = resource_path("catalog")
DEFAULT_METRICS = CATALOG_DIR / "metrics.yaml"
DEFAULT_EXPECTATIONS = CATALOG_DIR / "expectations.yaml"

RELATIONS = frozenset({"eq", "le", "ge", "range", "relative_ge", "relative_le"})
CLAIM_KINDS = frozenset({"definition", "theorem", "paper_experiment", "benchmark_sanity"})


@dataclass(frozen=True)
class MetricDefinition:
    metric_id: str
    track: str
    description: str
    direction: str
    unit: str
    aggregation: str
    formula: str = ""
    reference_keys: tuple[str, ...] = ()
    version: str = "1.0"
    display_name: str = ""
    question_answered: str = ""
    interpretation: str = ""
    good_value: str = ""
    bad_value: str = ""
    valid_range: tuple[float, float] | None = None
    scale_notes: str = ""
    applicability: str = ""
    failure_modes: tuple[str, ...] = ()
    ranking_role: str = "diagnostic"
    companion_metrics: tuple[str, ...] = ()
    paper_protocol: str = ""


@dataclass(frozen=True)
class ExpectationSpec:
    expectation_id: str
    family_id: str
    setting: str
    metric_id: str
    claim_kind: str
    relation: str
    target: Any
    tolerance: float
    required_assumptions: tuple[str, ...]
    reference_key: str
    claim_location: str
    comparison_family_id: str | None = None
    method_id: str | None = None

    def __post_init__(self) -> None:
        if self.claim_kind not in CLAIM_KINDS:
            raise ValueError(f"unsupported claim kind: {self.claim_kind}")
        if self.relation not in RELATIONS:
            raise ValueError(f"unsupported expectation relation: {self.relation}")
        if self.relation == "range":
            if not isinstance(self.target, (list, tuple)) or len(self.target) != 2:
                raise ValueError("range expectation target must contain two bounds")
        if self.relation.startswith("relative_") and not self.comparison_family_id:
            raise ValueError("relative expectation requires comparison_family_id")
        if not self.claim_location:
            raise ValueError("claim_location must be non-empty")


@dataclass(frozen=True)
class ExpectationResult:
    expectation_id: str
    status: str
    observed: Any = None
    target: Any = None
    comparison_observed: Any = None
    missing_assumptions: tuple[str, ...] = ()
    reason: str | None = None


def _items(path: str | Path, key: str) -> list[dict[str, Any]]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    values = raw.get(key, ())
    if not isinstance(values, list):
        raise ValueError(f"{key} must be a list")
    return [dict(value) for value in values]


def load_metric_definitions(
    path: str | Path = DEFAULT_METRICS,
) -> dict[str, MetricDefinition]:
    result: dict[str, MetricDefinition] = {}
    items = _items(path, "metrics")
    known_ids = {str(item.get("metric_id", "")) for item in items}
    primary = {
        "score_spearman", "corruption_auroc", "utility_recovery",
        "oracle_ratio", "gain_from_trade_ratio", "false_trade_count",
        "owner_lds", "owner_loo_correlation",
    }
    for item in items:
        metric_id = str(item.get("metric_id", ""))
        if not metric_id or metric_id in result:
            raise ValueError(f"missing or duplicate metric_id: {metric_id!r}")
        direction = str(item.get("direction", ""))
        if direction not in {"maximize", "minimize", "descriptive"}:
            raise ValueError(f"metric {metric_id} has invalid direction {direction!r}")
        companions = tuple(str(value) for value in item.get("companion_metrics", ()))
        unknown = sorted(set(companions) - known_ids)
        if unknown:
            raise ValueError(f"metric {metric_id} has unknown companion metric {unknown[0]!r}")
        unit = str(item["unit"])
        if item.get("valid_range") is not None:
            bounds = tuple(float(value) for value in item["valid_range"])
            if len(bounds) != 2 or bounds[0] > bounds[1]:
                raise ValueError(f"metric {metric_id} has invalid valid_range")
            valid_range = (bounds[0], bounds[1])
        elif unit in {"ratio", "boolean"}:
            valid_range = (0.0, 1.0)
        elif unit == "correlation":
            valid_range = (-1.0, 1.0)
        else:
            valid_range = None
        description = str(item["description"])
        if direction == "maximize":
            good_default, bad_default = "Higher is better.", "Lower is worse."
        elif direction == "minimize":
            good_default, bad_default = "Lower is better; zero is ideal when attainable.", "Higher is worse."
        else:
            good_default = bad_default = "Interpret jointly with the companion outcome metrics."
        role = str(item.get("ranking_role", "")) or (
            "primary" if metric_id in primary else
            "cost" if metric_id in {"runtime_seconds", "utility_calls"} else
            "guardrail" if any(token in metric_id for token in ("violation", "deviation", "false_trade", "rationality", "budget_balance")) else
            "diagnostic"
        )
        result[metric_id] = MetricDefinition(
            metric_id=metric_id,
            track=str(item["track"]),
            description=description,
            direction=direction,
            unit=unit,
            aggregation=str(item["aggregation"]),
            formula=str(item.get("formula", "")),
            reference_keys=tuple(str(value) for value in item.get("reference_keys", ())),
            version=str(item.get("version", "1.0")),
            display_name=str(item.get("display_name", metric_id.replace("_", " ").title())),
            question_answered=str(item.get("question_answered", f"How well does the method perform on {description.lower()}?")),
            interpretation=str(item.get("interpretation", description)),
            good_value=str(item.get("good_value", good_default)),
            bad_value=str(item.get("bad_value", bad_default)),
            valid_range=valid_range,
            scale_notes=str(item.get("scale_notes", f"Reported in {unit}; aggregate={item['aggregation']}.")),
            applicability=str(item.get("applicability", f"Applicable when the {metric_id} inputs and reference information are available.")),
            failure_modes=tuple(str(value) for value in item.get("failure_modes", ("Missing reference inputs", "Degenerate or constant outcomes"))),
            ranking_role=role,
            companion_metrics=companions,
            paper_protocol=str(item.get("paper_protocol", "Use case-level values, average seeds within each case, then macro-average cases.")),
        )
    return result


def load_expectations(
    path: str | Path = DEFAULT_EXPECTATIONS,
) -> tuple[ExpectationSpec, ...]:
    result: list[ExpectationSpec] = []
    seen: set[str] = set()
    for item in _items(path, "expectations"):
        expectation_id = str(item.get("expectation_id", ""))
        if not expectation_id or expectation_id in seen:
            raise ValueError(f"missing or duplicate expectation_id: {expectation_id!r}")
        seen.add(expectation_id)
        result.append(
            ExpectationSpec(
                expectation_id=expectation_id,
                family_id=str(item["family_id"]),
                setting=str(item["setting"]),
                metric_id=str(item["metric_id"]),
                claim_kind=str(item["claim_kind"]),
                relation=str(item["relation"]),
                target=item.get("target"),
                tolerance=float(item.get("tolerance", 0.0)),
                required_assumptions=tuple(
                    str(value) for value in item.get("required_assumptions", ())
                ),
                reference_key=str(item["reference_key"]),
                claim_location=str(item["claim_location"]),
                comparison_family_id=(
                    str(item["comparison_family_id"])
                    if item.get("comparison_family_id")
                    else None
                ),
                method_id=(str(item["method_id"]) if item.get("method_id") else None),
            )
        )
    return tuple(result)


def _metric_value(raw: Any) -> tuple[Any, bool, str | None]:
    if hasattr(raw, "applicable") and hasattr(raw, "value"):
        return raw.value, bool(raw.applicable), getattr(raw, "reason", None)
    if isinstance(raw, Mapping) and "applicable" in raw:
        return raw.get("value"), bool(raw["applicable"]), raw.get("reason")
    return raw, raw is not None, None


def _meets(observed: Any, comparison: Any, spec: ExpectationSpec) -> bool:
    tolerance = spec.tolerance
    if spec.relation == "eq":
        if isinstance(observed, bool) or isinstance(spec.target, bool):
            return observed is spec.target or observed == spec.target
        return abs(float(observed) - float(spec.target)) <= tolerance
    if spec.relation == "le":
        return float(observed) <= float(spec.target) + tolerance
    if spec.relation == "ge":
        return float(observed) + tolerance >= float(spec.target)
    if spec.relation == "range":
        lower, upper = spec.target
        return float(lower) - tolerance <= float(observed) <= float(upper) + tolerance
    if spec.relation == "relative_ge":
        return float(observed) + tolerance >= float(comparison)
    return float(observed) <= float(comparison) + tolerance


def evaluate_expectations(
    result: BenchmarkResult,
    case_metadata: Mapping[str, Any],
    specs: Iterable[ExpectationSpec],
) -> tuple[ExpectationResult, ...]:
    family = str(result.metadata.get("method_family", result.method_id))
    setting = str(result.metadata.get("benchmark_setting", ""))
    assumptions = frozenset(str(value) for value in case_metadata.get("assumptions", ()))
    evaluations: list[ExpectationResult] = []
    for spec in specs:
        if spec.family_id != family or spec.setting != setting:
            continue
        if spec.method_id is not None and spec.method_id != result.method_id:
            continue
        missing = tuple(sorted(set(spec.required_assumptions) - assumptions))
        if missing:
            evaluations.append(
                ExpectationResult(
                    spec.expectation_id,
                    "assumptions_unmet",
                    target=spec.target,
                    missing_assumptions=missing,
                )
            )
            continue
        if result.status != "completed" or spec.metric_id not in result.metrics:
            evaluations.append(
                ExpectationResult(
                    spec.expectation_id,
                    "not_applicable",
                    target=spec.target,
                    reason="result_or_metric_unavailable",
                )
            )
            continue
        observed, applicable, reason = _metric_value(result.metrics[spec.metric_id])
        if not applicable:
            evaluations.append(
                ExpectationResult(
                    spec.expectation_id,
                    "not_applicable",
                    observed=observed,
                    target=spec.target,
                    reason=reason or "metric_not_applicable",
                )
            )
            continue
        comparison = None
        if spec.relation.startswith("relative_"):
            comparisons = case_metadata.get("comparison_metrics", {})
            comparison = comparisons.get(spec.comparison_family_id, {}).get(spec.metric_id)
            if comparison is None:
                evaluations.append(
                    ExpectationResult(
                        spec.expectation_id,
                        "not_applicable",
                        observed=observed,
                        reason="comparison_metric_unavailable",
                    )
                )
                continue
        status = "met" if _meets(observed, comparison, spec) else "not_met"
        evaluations.append(
            ExpectationResult(
                spec.expectation_id,
                status,
                observed=observed,
                target=spec.target,
                comparison_observed=comparison,
            )
        )
    return tuple(evaluations)


__all__ = [
    "DEFAULT_EXPECTATIONS",
    "DEFAULT_METRICS",
    "ExpectationResult",
    "ExpectationSpec",
    "MetricDefinition",
    "evaluate_expectations",
    "load_expectations",
    "load_metric_definitions",
]
