"""Constraint qualification for mechanism leaderboard rows."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from .expectations import load_metric_definitions
from .leaderboard import LeaderboardRow
from .metrics import MetricValue
from .models import BenchmarkResult
from .resources import resource_path

CATALOG_DIR = resource_path("catalog")
DEFAULT_QUALIFICATION = CATALOG_DIR / "qualification.yaml"
RELATIONS = frozenset({"le", "ge", "eq"})
REQUIREMENTS = frozenset({"mandatory", "if_capability"})
QUALIFICATION_STATUSES = frozenset(
    {"pass", "fail", "not_auditable", "not_required"}
)


def normalize_qualification_status(value: object) -> str:
    """Validate the shared status vocabulary used by qualification diagnostics."""

    status = str(value).strip()
    if status not in QUALIFICATION_STATUSES:
        raise ValueError(f"invalid qualification status: {status!r}")
    return status


@dataclass(frozen=True)
class GuardrailRule:
    metric: str
    relation: str
    threshold: float
    requirement: str
    capability: str | None = None


@dataclass(frozen=True)
class QualificationPolicy:
    policy_id: str
    track: str
    settings: tuple[str, ...]
    rules: tuple[GuardrailRule, ...]


@dataclass(frozen=True)
class ConstraintProfile:
    track: str
    setting: str
    family_id: str
    method_id: str
    constraint_status: str
    rule_values: Mapping[str, float]
    passed_rules: tuple[str, ...] = ()
    failed_rules: tuple[str, ...] = ()
    missing_rules: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_qualification_policies(
    path: str | Path = DEFAULT_QUALIFICATION,
) -> tuple[QualificationPolicy, ...]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    items = raw.get("policies", ())
    metrics = load_metric_definitions()
    seen_ids: set[str] = set()
    seen_settings: set[tuple[str, str]] = set()
    policies = []
    for item in items:
        policy_id = str(item.get("policy_id", ""))
        if not policy_id or policy_id in seen_ids:
            raise ValueError(f"missing or duplicate qualification policy_id: {policy_id!r}")
        seen_ids.add(policy_id)
        track = str(item.get("track", ""))
        if track not in {"valuation", "procurement", "trading"}:
            raise ValueError(f"qualification policy {policy_id} has invalid track {track!r}")
        settings = tuple(str(value) for value in item.get("settings", ()))
        if not settings:
            raise ValueError(f"qualification policy {policy_id} requires settings")
        for setting in settings:
            key = (track, setting)
            if key in seen_settings:
                raise ValueError(f"duplicate qualification setting: {track}/{setting}")
            seen_settings.add(key)
        rules = []
        for value in item.get("rules", ()):
            metric = str(value.get("metric", ""))
            relation = str(value.get("relation", ""))
            requirement = str(value.get("requirement", ""))
            capability = str(value["capability"]) if value.get("capability") else None
            if metric not in metrics:
                raise ValueError(f"qualification policy {policy_id} has unknown metric {metric!r}")
            if relation not in RELATIONS:
                raise ValueError(f"qualification rule {metric} has invalid relation {relation!r}")
            if requirement not in REQUIREMENTS:
                raise ValueError(f"qualification rule {metric} has invalid requirement {requirement!r}")
            if requirement == "if_capability" and not capability:
                raise ValueError(f"qualification rule {metric} requires capability")
            rules.append(GuardrailRule(metric, relation, float(value["threshold"]), requirement, capability))
        policies.append(QualificationPolicy(policy_id, track, settings, tuple(rules)))
    return tuple(policies)


def _metric_number(result: BenchmarkResult, metric: str) -> float | None:
    if result.status != "completed":
        return None
    raw = result.metrics.get(metric)
    if isinstance(raw, MetricValue):
        if not raw.applicable:
            return None
        raw = raw.value
    elif isinstance(raw, Mapping) and "applicable" in raw:
        if not raw.get("applicable"):
            return None
        raw = raw.get("value")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _canonical_method(rows: Iterable[BenchmarkResult]) -> str:
    kinds = {row.method_id: str(row.metadata.get("implementation_kind", "native")) for row in rows}
    priority = {"native": 0, "external_adapter": 1}
    return min(kinds, key=lambda method: (priority.get(kinds[method], 2), method))


def _default_capabilities() -> dict[str, frozenset[str]]:
    from .runner import build_registry

    return {spec.method_id: spec.capabilities for spec in build_registry().specs()}


def _rule_holds(value: float, rule: GuardrailRule) -> bool:
    if rule.relation == "le":
        return value <= rule.threshold
    if rule.relation == "ge":
        return value >= rule.threshold
    return value == rule.threshold


def summarize_constraint_profiles(
    results: Iterable[BenchmarkResult],
    *,
    policies: Iterable[QualificationPolicy] | None = None,
    capabilities_by_method: Mapping[str, frozenset[str]] | None = None,
) -> tuple[ConstraintProfile, ...]:
    materialized = tuple(results)
    policy_index = {
        (policy.track, setting): policy
        for policy in (tuple(policies) if policies is not None else load_qualification_policies())
        for setting in policy.settings
    }
    fallback_capabilities: Mapping[str, frozenset[str]] | None = capabilities_by_method
    groups: dict[tuple[str, str, str], list[BenchmarkResult]] = {}
    for row in materialized:
        setting = str(row.metadata.get("benchmark_setting", "unknown"))
        family = str(row.metadata.get("method_family", row.method_id))
        groups.setdefault((row.track, setting, family), []).append(row)

    profiles = []
    for (track, setting, family), family_rows in sorted(groups.items()):
        method_id = _canonical_method(family_rows)
        rows = [row for row in family_rows if row.method_id == method_id]
        policy = policy_index.get((track, setting))
        if policy is None:
            profiles.append(ConstraintProfile(track, setting, family, method_id, "not_required", {}))
            continue
        declared = {str(value) for row in rows for value in row.metadata.get("method_capabilities", ())}
        if not declared:
            if fallback_capabilities is None:
                fallback_capabilities = _default_capabilities()
            declared = set(fallback_capabilities.get(method_id, frozenset()))
        values: dict[str, float] = {}
        passed: list[str] = []
        failed: list[str] = []
        missing: list[str] = []
        for rule in policy.rules:
            if rule.requirement == "if_capability" and rule.capability not in declared:
                continue
            observed = [_metric_number(row, rule.metric) for row in rows]
            if not observed or any(value is None for value in observed):
                missing.append(rule.metric)
                continue
            finite = [float(value) for value in observed if value is not None]
            summary = min(finite) if rule.relation == "ge" else max(finite)
            values[rule.metric] = summary
            (passed if all(_rule_holds(value, rule) for value in finite) else failed).append(rule.metric)
        status = "fail" if failed else "not_auditable" if missing else "pass"
        profiles.append(ConstraintProfile(track, setting, family, method_id, status, values, tuple(passed), tuple(failed), tuple(missing)))
    return tuple(profiles)


def attach_constraint_ranks(
    rows: Iterable[LeaderboardRow], profiles: Iterable[ConstraintProfile]
) -> tuple[LeaderboardRow, ...]:
    profile_index = {(profile.track, profile.setting, profile.family_id): profile for profile in profiles}
    enriched = []
    for row in rows:
        profile = profile_index.get((row.track, row.setting, row.family_id))
        status = profile.constraint_status if profile else "not_auditable"
        reason = "" if status in {"pass", "not_required"} else (
            ";".join(profile.failed_rules or profile.missing_rules) if profile else "missing_constraint_profile"
        )
        enriched.append(replace(row, constraint_status=status, constraint_reason=reason))
    groups: dict[tuple[str, str], list[LeaderboardRow]] = {}
    for row in enriched:
        if row.coverage_ratio == 1.0 and row.mean is not None and row.constraint_status in {"pass", "not_required"}:
            groups.setdefault((row.track, row.setting), []).append(row)
    ranks: dict[tuple[str, str, str], int] = {}
    for (track, setting), candidates in groups.items():
        direction = candidates[0].direction
        ordered = sorted(candidates, key=lambda row: ((-float(row.mean) if direction == "maximize" else float(row.mean)), row.family_id))
        previous = None
        previous_rank = 0
        for position, row in enumerate(ordered, start=1):
            rounded = round(float(row.mean), 12)
            if previous is None or rounded != previous:
                previous, previous_rank = rounded, position
            ranks[(track, setting, row.family_id)] = previous_rank
    return tuple(replace(row, constraint_qualified_rank=ranks.get((row.track, row.setting, row.family_id))) for row in enriched)


__all__ = [
    "ConstraintProfile", "GuardrailRule", "QUALIFICATION_STATUSES",
    "QualificationPolicy",
    "attach_constraint_ranks", "load_qualification_policies",
    "normalize_qualification_status", "summarize_constraint_profiles",
]
