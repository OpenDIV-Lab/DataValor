"""Fail-closed mechanism risk cards for the KDD headline suite.

The cards expose evidence boundaries and affected roles.  They deliberately do
not assign a risk score, rank mechanisms, or certify a mechanism as fair/safe.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Sequence

import yaml

if TYPE_CHECKING:
    from .kdd_readiness import KDDTarget

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG = PACKAGE_ROOT / "catalog" / "mechanism_risk_cards.yaml"
DEFAULT_TARGET = PACKAGE_ROOT / "catalog" / "kdd_submission.yaml"
DEFAULT_METRIC_CATALOG = PACKAGE_ROOT / "catalog" / "metrics.yaml"
DEFAULT_CORE_MANIFEST = PACKAGE_ROOT / "reproduction" / "kdd2027_core_manifest.json"
DEFAULT_OUTPUT_DIR = PACKAGE_ROOT / "outputs" / "kdd_mechanism_risks"

RISK_DIMENSIONS = (
    "score_or_allocation_incidence",
    "payment_incidence",
    "individual_rationality",
    "budget_feasibility",
    "manipulation_evidence",
    "subgroup_fairness",
    "privacy_externality",
)
ALLOWED_STATUSES = frozenset({"audited_scope", "not_auditable", "not_applicable"})
REQUIRED_PROHIBITED_USES = frozenset(
    {"automatic_compensation", "automatic_market_access"}
)
OUTPUT_NAMES = (
    "mechanism_risk_cards.csv",
    "dimension_audit.csv",
    "summary.json",
    "report.md",
)
_PROHIBITED_COMPOSITE_KEYS = frozenset(
    {
        "risk_score",
        "overall_risk",
        "fairness_score",
        "safety_score",
        "winner",
        "ranking",
        "rank",
        "fairness_badge",
        "safety_badge",
        "deployment_approval",
    }
)
FROZEN_HEADLINE_TRACKS = {
    "shapley_exact": "valuation",
    "tmc_shapley": "valuation",
    "banzhaf_exact": "valuation",
    "knn_shapley": "valuation",
    "volume_shapley": "valuation",
    "robust_volume_shapley": "valuation",
    "generalized_proportional_share": "procurement",
    "cgl_deterministic": "procurement",
    "cgl_randomized": "procurement",
    "jt_greedy_tm": "procurement",
    "jt_random_eom": "procurement",
    "jt_deterministic_eom": "procurement",
    "mcafee": "trading",
    "trade_reduction": "trading",
    "sbba": "trading",
    "lottery_muda": "trading",
    "vickrey_muda": "trading",
}
_CATALOG_KEYS = frozenset(
    {"schema_version", "no_cross_method_composite", "dimension_templates", "cards"}
)
_CARD_KEYS = frozenset(
    {
        "method_id",
        "track",
        "affected_roles",
        "potential_beneficiaries",
        "potentially_burdened_roles",
        "prohibited_uses",
        "deployment_boundary",
        "limitations",
        "dimensions",
    }
)
_DIMENSION_KEYS = frozenset(
    {"status", "scope", "evidence_metric_ids", "evidence_paths", "reason"}
)


@dataclass(frozen=True)
class MetricEvidenceCoverage:
    metric_id: str
    source_path: str
    applicable_rows: int
    observed_rows: int
    total_method_rows: int
    missing_reasons: tuple[tuple[str, int], ...]

    @property
    def complete(self) -> bool:
        return (
            self.total_method_rows > 0
            and self.observed_rows == self.total_method_rows
            and self.applicable_rows == self.total_method_rows
        )


@dataclass(frozen=True)
class RiskDimension:
    status: str
    scope: str
    evidence_metric_ids: tuple[str, ...]
    evidence_paths: tuple[str, ...]
    reason: str
    evidence_coverage: tuple[MetricEvidenceCoverage, ...]


@dataclass(frozen=True)
class MechanismRiskCard:
    method_id: str
    track: str
    affected_roles: tuple[str, ...]
    potential_beneficiaries: tuple[str, ...]
    potentially_burdened_roles: tuple[str, ...]
    prohibited_uses: frozenset[str]
    deployment_boundary: str
    limitations: tuple[str, ...]
    dimensions: Mapping[str, RiskDimension]


@dataclass(frozen=True)
class MechanismRiskCatalog:
    schema_version: str
    no_cross_method_composite: bool
    cards: tuple[MechanismRiskCard, ...]
    source_path: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mapping(raw: Any, label: str) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return {str(key): value for key, value in raw.items()}


def _exact_keys(raw: Mapping[str, Any], allowed: frozenset[str], label: str) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError(f"{label} contains unknown fields: {unknown}")


def _strings(raw: Any, label: str) -> tuple[str, ...]:
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{label} must be a non-empty list")
    if any(not isinstance(item, str) for item in raw):
        raise ValueError(f"{label} must contain unique non-empty strings")
    values = tuple(item.strip() for item in raw)
    if any(not item for item in values) or len(set(values)) != len(values):
        raise ValueError(f"{label} must contain unique non-empty strings")
    return values


def _nonempty(raw: Any, label: str) -> str:
    if not isinstance(raw, str):
        raise ValueError(f"{label} must be a non-empty string")
    value = raw.strip()
    if not value:
        raise ValueError(f"{label} must be non-empty")
    return value


def _relative_existing_file(raw: Any, root: Path, label: str) -> str:
    value = _nonempty(raw, label)
    candidate = Path(value)
    if candidate.is_absolute():
        raise ValueError(f"{label} must be repository-relative")
    resolved_root = root.resolve()
    try:
        resolved = (resolved_root / candidate).resolve()
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"{label} escapes repository root") from exc
    if not resolved.is_file() or resolved.is_symlink():
        raise ValueError(f"{label} must identify an existing regular file: {value}")
    return candidate.as_posix()


def _reject_composite_keys(raw: Any, label: str = "catalog") -> None:
    if isinstance(raw, Mapping):
        for key, value in raw.items():
            normalized = str(key).strip().lower()
            if normalized in _PROHIBITED_COMPOSITE_KEYS:
                raise ValueError(f"{label} contains prohibited composite field {key}")
            _reject_composite_keys(value, f"{label}.{key}")
    elif isinstance(raw, list):
        for index, value in enumerate(raw):
            _reject_composite_keys(value, f"{label}[{index}]")


def _metric_tracks(root: Path) -> dict[str, str]:
    raw = _mapping(
        yaml.safe_load((root / "benchmark/catalog/metrics.yaml").read_text(encoding="utf-8"))
        or {},
        "metric_catalog",
    )
    metrics = raw.get("metrics")
    if not isinstance(metrics, list):
        raise ValueError("metric_catalog.metrics must be a list")
    result: dict[str, str] = {}
    for index, item_raw in enumerate(metrics):
        item = _mapping(item_raw, f"metric_catalog.metrics[{index}]")
        metric_id = _nonempty(item.get("metric_id"), f"metric_catalog.metrics[{index}].metric_id")
        track = _nonempty(item.get("track"), f"metric_catalog.metrics[{index}].track")
        if metric_id in result:
            raise ValueError(f"duplicate metric in metric catalog: {metric_id}")
        result[metric_id] = track
    return result


def _release_bound_paths(root: Path) -> frozenset[str]:
    source = root / "benchmark/reproduction/kdd2027_core_manifest.json"
    raw = _mapping(json.loads(source.read_text(encoding="utf-8")), "core_manifest")
    paths = {
        _nonempty(item.get("path"), f"core_manifest.artifacts[{index}].path")
        for index, item_raw in enumerate(raw.get("artifacts", []))
        for item in [_mapping(item_raw, f"core_manifest.artifacts[{index}]")]
    }
    scientific = _mapping(raw.get("scientific_results"), "core_manifest.scientific_results")
    paths.add(_nonempty(scientific.get("path"), "core_manifest.scientific_results.path"))
    return frozenset(paths)


def _jsonl_metric_coverage(
    path: Path,
    relative_path: str,
    *,
    method_id: str,
    track: str,
    metric_id: str,
) -> MetricEvidenceCoverage | None:
    if path.suffix != ".jsonl":
        return None
    method_rows: list[Mapping[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = _mapping(json.loads(line), f"{relative_path}:{line_number}")
        if row.get("method_id") == method_id and row.get("track") == track:
            method_rows.append(row)
    if not method_rows:
        return None
    metric_rows: list[Mapping[str, Any]] = []
    for row in method_rows:
        metrics = _mapping(row.get("metrics"), f"{relative_path}.{method_id}.metrics")
        if metric_id in metrics:
            metric_rows.append(
                _mapping(metrics[metric_id], f"{relative_path}.{method_id}.{metric_id}")
            )
    if not metric_rows:
        return None
    applicable = sum(item.get("applicable") is True for item in metric_rows)
    reasons = Counter(
        str(item.get("reason") or "unspecified")
        for item in metric_rows
        if item.get("applicable") is not True
    )
    return MetricEvidenceCoverage(
        metric_id=metric_id,
        source_path=relative_path,
        applicable_rows=applicable,
        observed_rows=len(metric_rows),
        total_method_rows=len(method_rows),
        missing_reasons=tuple(sorted(reasons.items())),
    )


def _metric_coverage(
    *,
    method_id: str,
    track: str,
    metric_id: str,
    evidence_paths: Sequence[str],
    root: Path,
) -> MetricEvidenceCoverage:
    for relative_path in evidence_paths:
        coverage = _jsonl_metric_coverage(
            root / relative_path,
            relative_path,
            method_id=method_id,
            track=track,
            metric_id=metric_id,
        )
        if coverage is not None:
            return coverage
    raise ValueError(
        f"{method_id}.{metric_id} has no method-level JSONL coverage in cited evidence"
    )


def load_mechanism_risk_cards(
    path: str | Path = DEFAULT_CATALOG,
    *,
    target: KDDTarget | None = None,
    repository_root: str | Path,
) -> MechanismRiskCatalog:
    """Load risk cards and require exact coverage of the frozen headline suite."""

    source = Path(path)
    raw = _mapping(yaml.safe_load(source.read_text(encoding="utf-8")) or {}, "catalog")
    _reject_composite_keys(raw)
    _exact_keys(raw, _CATALOG_KEYS, "catalog")
    if str(raw.get("schema_version", "")) != "1.0":
        raise ValueError("unsupported mechanism risk-card schema_version")
    if raw.get("no_cross_method_composite") is not True:
        raise ValueError("no_cross_method_composite must be true")
    if target is None:
        from .kdd_readiness import load_kdd_target

        target = load_kdd_target(DEFAULT_TARGET)
    root = Path(repository_root)
    metric_tracks = _metric_tracks(root)
    release_bound_paths = _release_bound_paths(root)
    cards_raw = raw.get("cards")
    if not isinstance(cards_raw, list) or not cards_raw:
        raise ValueError("cards must be a non-empty list")

    expected_tracks = {
        method_id: track
        for track, flagship in target.flagships.items()
        for method_id in flagship.method_ids
    }
    if expected_tracks != FROZEN_HEADLINE_TRACKS:
        raise ValueError(
            "frozen headline suite mismatch: "
            f"missing={sorted(set(FROZEN_HEADLINE_TRACKS) - set(expected_tracks))}, "
            f"extra={sorted(set(expected_tracks) - set(FROZEN_HEADLINE_TRACKS))}"
        )
    cards: list[MechanismRiskCard] = []
    observed_ids: list[str] = []
    for index, raw_card in enumerate(cards_raw):
        card = _mapping(raw_card, f"cards[{index}]")
        _exact_keys(card, _CARD_KEYS, f"cards[{index}]")
        method_id = _nonempty(card.get("method_id"), f"cards[{index}].method_id")
        track = _nonempty(card.get("track"), f"cards[{index}].track")
        observed_ids.append(method_id)
        expected_track = expected_tracks.get(method_id)
        if expected_track is not None and track != expected_track:
            raise ValueError(
                f"track mismatch for {method_id}: expected {expected_track}, observed {track}"
            )
        prohibited_uses = frozenset(
            _strings(card.get("prohibited_uses"), f"{method_id}.prohibited_uses")
        )
        missing_prohibited = sorted(REQUIRED_PROHIBITED_USES - prohibited_uses)
        if missing_prohibited:
            raise ValueError(
                f"{method_id}.prohibited_uses missing required values: {missing_prohibited}"
            )

        raw_dimensions = _mapping(card.get("dimensions"), f"{method_id}.dimensions")
        if set(raw_dimensions) != set(RISK_DIMENSIONS):
            raise ValueError(
                f"{method_id} dimension coverage mismatch: "
                f"expected {list(RISK_DIMENSIONS)}, observed {sorted(raw_dimensions)}"
            )
        dimensions: dict[str, RiskDimension] = {}
        for dimension_id in RISK_DIMENSIONS:
            item = _mapping(raw_dimensions[dimension_id], f"{method_id}.{dimension_id}")
            _exact_keys(item, _DIMENSION_KEYS, f"{method_id}.{dimension_id}")
            status = _nonempty(item.get("status"), f"{method_id}.{dimension_id}.status")
            if status not in ALLOWED_STATUSES:
                raise ValueError(
                    f"{method_id}.{dimension_id} has unsupported status {status}"
                )
            scope_raw = item.get("scope", "")
            reason_raw = item.get("reason", "")
            if not isinstance(scope_raw, str) or not isinstance(reason_raw, str):
                raise ValueError(
                    f"{method_id}.{dimension_id} scope and reason must be strings"
                )
            scope = scope_raw.strip()
            reason = reason_raw.strip()
            metric_ids_raw = item.get("evidence_metric_ids", [])
            evidence_paths_raw = item.get("evidence_paths", [])
            metric_ids = (
                _strings(metric_ids_raw, f"{method_id}.{dimension_id}.evidence_metric_ids")
                if metric_ids_raw
                else ()
            )
            if evidence_paths_raw and not isinstance(evidence_paths_raw, list):
                raise ValueError(f"{method_id}.{dimension_id}.evidence_paths must be a list")
            evidence_paths = (
                tuple(
                    _relative_existing_file(
                        value,
                        root,
                        f"{method_id}.{dimension_id}.evidence_paths[{path_index}]",
                    )
                    for path_index, value in enumerate(evidence_paths_raw)
                )
                if evidence_paths_raw
                else ()
            )
            coverage: tuple[MetricEvidenceCoverage, ...] = ()
            if status == "audited_scope":
                if not scope or not metric_ids or not evidence_paths:
                    raise ValueError(
                        f"audited_scope {method_id}.{dimension_id} requires scope, "
                        "evidence_metric_ids, and evidence_paths"
                    )
                unbound_paths = sorted(set(evidence_paths) - release_bound_paths)
                if unbound_paths:
                    raise ValueError(
                        f"{method_id}.{dimension_id} cites evidence paths not bound by "
                        f"the core release manifest: {unbound_paths}"
                    )
                for metric_id in metric_ids:
                    metric_track = metric_tracks.get(metric_id)
                    if metric_track is None:
                        raise ValueError(
                            f"{method_id}.{dimension_id} cites unknown metric {metric_id}"
                        )
                    if metric_track != track:
                        raise ValueError(
                            f"{method_id}.{dimension_id} metric {metric_id} belongs to "
                            f"track {metric_track}, not {track}"
                        )
                coverage = tuple(
                    _metric_coverage(
                        method_id=method_id,
                        track=track,
                        metric_id=metric_id,
                        evidence_paths=evidence_paths,
                        root=root,
                    )
                    for metric_id in metric_ids
                )
            elif not reason:
                raise ValueError(
                    f"{status} {method_id}.{dimension_id} requires a non-empty reason"
                )
            dimensions[dimension_id] = RiskDimension(
                status=status,
                scope=scope,
                evidence_metric_ids=metric_ids,
                evidence_paths=evidence_paths,
                reason=reason,
                evidence_coverage=coverage,
            )

        risk_card = MechanismRiskCard(
            method_id=method_id,
            track=track,
            affected_roles=_strings(card.get("affected_roles"), f"{method_id}.affected_roles"),
            potential_beneficiaries=_strings(
                card.get("potential_beneficiaries"),
                f"{method_id}.potential_beneficiaries",
            ),
            potentially_burdened_roles=_strings(
                card.get("potentially_burdened_roles"),
                f"{method_id}.potentially_burdened_roles",
            ),
            prohibited_uses=prohibited_uses,
            deployment_boundary=_nonempty(
                card.get("deployment_boundary"), f"{method_id}.deployment_boundary"
            ),
            limitations=_strings(card.get("limitations"), f"{method_id}.limitations"),
            dimensions=dimensions,
        )
        if not any(item.status == "not_auditable" for item in dimensions.values()):
            raise ValueError(f"{method_id} must expose at least one not_auditable dimension")
        cards.append(risk_card)

    duplicates = sorted(
        method_id for method_id, count in Counter(observed_ids).items() if count > 1
    )
    observed = set(observed_ids)
    expected = set(expected_tracks)
    if duplicates or observed != expected:
        raise ValueError(
            "headline coverage mismatch: "
            f"missing={sorted(expected - observed)}, extra={sorted(observed - expected)}, "
            f"duplicates={duplicates}"
        )
    return MechanismRiskCatalog(
        schema_version="1.0",
        no_cross_method_composite=True,
        cards=tuple(sorted(cards, key=lambda item: (item.track, item.method_id))),
        source_path=str(source),
    )


def _repository_relative(path: Path, root: Path, label: str) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"{label} must be inside repository_root") from exc


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"


def _csv_text(columns: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in columns})
    return buffer.getvalue()


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _coverage_text(coverage: Sequence[MetricEvidenceCoverage]) -> str:
    parts: list[str] = []
    for item in coverage:
        reasons = ",".join(f"{reason}={count}" for reason, count in item.missing_reasons)
        suffix = f"; missing:{reasons}" if reasons else ""
        parts.append(
            f"{item.metric_id}={item.applicable_rows}/{item.total_method_rows} "
            f"applicable ({item.observed_rows} observed){suffix}"
        )
    return " | ".join(parts)


def build_mechanism_risk_artifacts(
    catalog_path: str | Path = DEFAULT_CATALOG,
    target_path: str | Path = DEFAULT_TARGET,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    *,
    repository_root: str | Path,
) -> dict[str, Any]:
    """Build deterministic non-composite risk-card review artifacts."""

    root = Path(repository_root)
    catalog_file = Path(catalog_path)
    target_file = Path(target_path)
    from .kdd_readiness import load_kdd_target

    target = load_kdd_target(target_file)
    catalog = load_mechanism_risk_cards(
        catalog_file,
        target=target,
        repository_root=root,
    )
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)

    card_rows: list[dict[str, str]] = []
    dimension_rows: list[dict[str, str]] = []
    status_counts: Counter[str] = Counter()
    audited_complete_count = 0
    audited_partial_count = 0
    for card in catalog.cards:
        card_rows.append(
            {
                "method_id": card.method_id,
                "track": card.track,
                "affected_roles": ";".join(card.affected_roles),
                "potential_beneficiaries": ";".join(card.potential_beneficiaries),
                "potentially_burdened_roles": ";".join(
                    card.potentially_burdened_roles
                ),
                "prohibited_uses": ";".join(sorted(card.prohibited_uses)),
                "deployment_boundary": card.deployment_boundary,
                "limitations": ";".join(card.limitations),
            }
        )
        for dimension_id in RISK_DIMENSIONS:
            dimension = card.dimensions[dimension_id]
            status_counts[dimension.status] += 1
            coverage_complete = bool(dimension.evidence_coverage) and all(
                item.complete for item in dimension.evidence_coverage
            )
            if dimension.status == "audited_scope":
                if coverage_complete:
                    audited_complete_count += 1
                else:
                    audited_partial_count += 1
            dimension_rows.append(
                {
                    "method_id": card.method_id,
                    "track": card.track,
                    "dimension_id": dimension_id,
                    "status": dimension.status,
                    "scope": dimension.scope,
                    "reason": dimension.reason,
                    "evidence_metric_ids": ";".join(dimension.evidence_metric_ids),
                    "evidence_paths": ";".join(dimension.evidence_paths),
                    "evidence_coverage_complete": (
                        str(coverage_complete).lower()
                        if dimension.status == "audited_scope"
                        else ""
                    ),
                    "evidence_coverage": _coverage_text(
                        dimension.evidence_coverage
                    ),
                }
            )

    _write_text(
        destination / "mechanism_risk_cards.csv",
        _csv_text(
            (
                "method_id",
                "track",
                "affected_roles",
                "potential_beneficiaries",
                "potentially_burdened_roles",
                "prohibited_uses",
                "deployment_boundary",
                "limitations",
            ),
            card_rows,
        ),
    )
    _write_text(
        destination / "dimension_audit.csv",
        _csv_text(
            (
                "method_id",
                "track",
                "dimension_id",
                "status",
                "scope",
                "reason",
                "evidence_metric_ids",
                "evidence_paths",
                "evidence_coverage_complete",
                "evidence_coverage",
            ),
            dimension_rows,
        ),
    )
    summary = {
        "schema_version": "1.0",
        "report_kind": "headline_mechanism_risk_cards",
        "card_count": len(card_rows),
        "dimension_count": len(RISK_DIMENSIONS),
        "dimension_row_count": len(dimension_rows),
        "track_counts": dict(sorted(Counter(row["track"] for row in card_rows).items())),
        "status_counts": dict(sorted(status_counts.items())),
        "audited_dimension_complete_count": audited_complete_count,
        "audited_dimension_partial_count": audited_partial_count,
        "no_cross_method_composite": True,
        "interpretation_boundary": (
            "Statuses describe what this benchmark audits. They are not risk levels, "
            "fairness certifications, deployment approvals, or mechanism rankings."
        ),
    }
    _write_text(destination / "summary.json", _canonical_json(summary))

    report_lines = [
        "# Headline mechanism risk-card audit",
        "",
        f"This report covers all {len(card_rows)} frozen headline mechanisms. It records affected roles,",
        "possible benefits and burdens, prohibited uses, and evidence scope. It deliberately",
        "does **not** compute a risk/fairness score, declare a safe mechanism, or combine",
        "dimensions into a winner.",
        "",
        "## Coverage",
        "",
        f"- Cards: {len(card_rows)}",
        f"- Dimension rows: {len(dimension_rows)} ({len(RISK_DIMENSIONS)} per card)",
        f"- Fully covered audited dimensions: {audited_complete_count}",
        f"- Partially covered audited dimensions: {audited_partial_count}",
        "- Status counts: " + ", ".join(
            f"`{status}`={count}" for status, count in sorted(status_counts.items())
        ),
        "",
        "## Method-level boundaries",
        "",
        "| Track | Method | Audited scope | Not auditable | Deployment boundary |",
        "|---|---|---:|---:|---|",
    ]
    for card in catalog.cards:
        counts = Counter(item.status for item in card.dimensions.values())
        boundary = card.deployment_boundary.replace("|", "\\|")
        report_lines.append(
            f"| {card.track} | `{card.method_id}` | {counts['audited_scope']} | "
            f"{counts['not_auditable']} | {boundary} |"
        )
    report_lines.extend(
        [
            "",
            "`not_auditable` is an evidence gap, never a zero-risk value. See the two CSV",
            "files for the per-role and per-dimension records. Likewise, `audited_scope`",
            "does not imply complete coverage: `dimension_audit.csv` reports applicable/total",
            "method rows and every missingness reason for each cited metric.",
            "",
        ]
    )
    _write_text(destination / "report.md", "\n".join(report_lines))

    outputs = {
        name: {"sha256": _sha256(destination / name), "bytes": (destination / name).stat().st_size}
        for name in OUTPUT_NAMES
    }
    manifest = {
        "schema_version": "1.0",
        "manifest_kind": "mechanism_risk_cards",
        "inputs": {
            "catalog": {
                "path": _repository_relative(catalog_file, root, "catalog"),
                "sha256": _sha256(catalog_file),
            },
            "target": {
                "path": _repository_relative(target_file, root, "target"),
                "sha256": _sha256(target_file),
            },
        },
        "outputs": outputs,
        "card_count": len(card_rows),
        "dimension_row_count": len(dimension_rows),
        "status_counts": dict(sorted(status_counts.items())),
        "no_cross_method_composite": True,
    }
    _write_text(destination / "manifest.json", _canonical_json(manifest))
    verified = verify_mechanism_risk_artifacts(
        destination / "manifest.json",
        repository_root=root,
    )
    if not verified["valid"]:
        raise ValueError(f"built mechanism risk artifacts failed verification: {verified}")
    return manifest


def verify_mechanism_risk_artifacts(
    manifest_path: str | Path,
    *,
    repository_root: str | Path,
) -> dict[str, Any]:
    """Verify catalog semantics plus every derived output byte."""

    source = Path(manifest_path)
    root = Path(repository_root)
    errors: list[str] = []
    card_count = 0
    dimension_row_count = 0
    no_composite = False
    try:
        raw = _mapping(json.loads(source.read_text(encoding="utf-8")), "manifest")
        if raw.get("schema_version") != "1.0":
            errors.append("unsupported_schema_version")
        if raw.get("manifest_kind") != "mechanism_risk_cards":
            errors.append("invalid_manifest_kind")
        card_count = int(raw.get("card_count", -1))
        dimension_row_count = int(raw.get("dimension_row_count", -1))
        no_composite = raw.get("no_cross_method_composite") is True
        if not no_composite:
            errors.append("cross_method_composite_not_prohibited")

        inputs = _mapping(raw.get("inputs"), "manifest.inputs")
        resolved_inputs: dict[str, Path] = {}
        for name in ("catalog", "target"):
            binding = _mapping(inputs.get(name), f"manifest.inputs.{name}")
            try:
                relative_path = _relative_existing_file(
                    binding.get("path"), root, f"manifest.inputs.{name}.path"
                )
            except ValueError as exc:
                errors.append(f"invalid_input_path:{name}:{exc}")
                continue
            path = root / relative_path
            resolved_inputs[name] = path
            if _sha256(path) != binding.get("sha256"):
                errors.append(f"input_hash_mismatch:{name}")
        if not any(
            error.startswith(
                ("missing_input:", "invalid_input_path:", "input_hash_mismatch:")
            )
            for error in errors
        ):
            from .kdd_readiness import load_kdd_target

            target = load_kdd_target(resolved_inputs["target"])
            catalog = load_mechanism_risk_cards(
                resolved_inputs["catalog"],
                target=target,
                repository_root=root,
            )
            expected_card_count = len(catalog.cards)
            expected_dimension_rows = expected_card_count * len(RISK_DIMENSIONS)
            if card_count != expected_card_count:
                errors.append("card_count_mismatch")
            if dimension_row_count != expected_dimension_rows:
                errors.append("dimension_row_count_mismatch")

        outputs = _mapping(raw.get("outputs"), "manifest.outputs")
        if set(outputs) != set(OUTPUT_NAMES):
            errors.append("output_set_mismatch")
        for name in OUTPUT_NAMES:
            binding = outputs.get(name)
            if not isinstance(binding, Mapping):
                errors.append(f"missing_output_binding:{name}")
                continue
            path = source.parent / name
            if not path.is_file() or path.is_symlink():
                errors.append(f"missing_output:{name}")
                continue
            if _sha256(path) != binding.get("sha256"):
                errors.append(f"hash_mismatch:{name}")
            if path.stat().st_size != binding.get("bytes"):
                errors.append(f"byte_count_mismatch:{name}")
    except (OSError, ValueError, TypeError, json.JSONDecodeError, yaml.YAMLError) as exc:
        errors.append(f"invalid_manifest:{exc}")
    return {
        "valid": not errors,
        "errors": errors,
        "card_count": card_count,
        "dimension_row_count": dimension_row_count,
        "no_cross_method_composite": no_composite,
    }


__all__ = [
    "DEFAULT_CATALOG",
    "DEFAULT_OUTPUT_DIR",
    "DEFAULT_TARGET",
    "MechanismRiskCard",
    "MechanismRiskCatalog",
    "RISK_DIMENSIONS",
    "RiskDimension",
    "build_mechanism_risk_artifacts",
    "load_mechanism_risk_cards",
    "verify_mechanism_risk_artifacts",
]
