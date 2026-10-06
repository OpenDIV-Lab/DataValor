"""Configuration loading and deterministic benchmark execution."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from .data import (
    make_analytic_valuation_cases,
    make_procurement_cases,
    make_real_valuation_cases,
    make_trade_cases,
)
from .methods import (
    OptionalMethodUnavailable,
    register_procurement_methods,
    register_trading_methods,
    register_valuation_methods,
)
from .metrics import (
    evaluate_procurement_metrics,
    evaluate_trading_metrics,
    evaluate_valuation_metrics,
)
from .models import BenchmarkResult
from .outcomes import serialize_outcome
from .provenance import load_provenance
from .registry import MethodRegistry, validate_output
from .settings.procurement import (
    make_procurement_additive_cases,
    make_procurement_concentration_cases,
    make_procurement_ml_cases,
    make_procurement_submodular_cases,
)
from .settings.trading import (
    make_bilateral_trade_cases,
    make_correlated_trade_cases,
    make_double_auction_cases,
    make_market_thickness_cases,
    make_no_trade_cases,
)
from .settings.valuation import (
    make_valuation_axiom_cases,
    make_valuation_contribution_cases,
    make_valuation_corruption_cases,
    make_valuation_noise_cases,
    make_valuation_replication_cases,
    make_valuation_structural_cases,
)

TRACKS = ("valuation", "procurement", "trading")


@dataclass(frozen=True)
class BenchmarkConfig:
    name: str
    output_dir: str
    seeds: tuple[int, ...]
    methods: Mapping[str, Mapping[str, Mapping[str, Any]]]
    case_ids: Mapping[str, tuple[str, ...]]
    strategic_audit: bool = True
    result_metric_ids: Mapping[str, tuple[str, ...]] | None = None
    result_diagnostic_keys: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("benchmark name must be non-empty")
        if not self.seeds:
            raise ValueError("at least one seed is required")
        if self.result_metric_ids is not None:
            unknown_tracks = set(self.result_metric_ids) - set(TRACKS)
            if unknown_tracks:
                raise ValueError(
                    f"result_metric_ids contains unknown tracks: {sorted(unknown_tracks)}"
                )


def _method_config(entries: object) -> dict[str, Mapping[str, Any]]:
    if entries is None:
        return {}
    if isinstance(entries, Mapping):
        return {str(key): dict(value or {}) for key, value in entries.items()}
    result = {}
    for entry in entries:
        if isinstance(entry, str):
            result[entry] = {}
        else:
            result[str(entry["id"])] = dict(entry.get("params", {}))
    return result


def load_config(path: str | Path) -> BenchmarkConfig:
    config_path = Path(path)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    method_section = raw.get("methods", {})
    case_section = raw.get("cases", {})
    result_contract = raw.get("result_contract")
    metric_ids = None
    diagnostic_keys = None
    if result_contract is not None:
        metric_ids = {
            track: tuple(str(metric_id) for metric_id in result_contract.get("metric_ids", {}).get(track, ()))
            for track in TRACKS
        }
        diagnostic_keys = tuple(
            str(key) for key in result_contract.get("diagnostic_keys", ())
        )
    return BenchmarkConfig(
        name=str(raw.get("name", config_path.stem)),
        output_dir=str(raw.get("output_dir", "benchmark/outputs/mvp")),
        seeds=tuple(int(seed) for seed in raw.get("seeds", (0,))),
        methods={track: _method_config(method_section.get(track, ())) for track in TRACKS},
        case_ids={
            track: tuple(str(case_id) for case_id in case_section.get(track, ()))
            for track in TRACKS
        },
        strategic_audit=bool(raw.get("strategic_audit", True)),
        result_metric_ids=metric_ids,
        result_diagnostic_keys=diagnostic_keys,
    )


def build_registry() -> MethodRegistry:
    registry = MethodRegistry()
    register_valuation_methods(registry)
    register_procurement_methods(registry)
    register_trading_methods(registry)
    return registry


def build_cases(seed: int = 42) -> dict[str, tuple[Any, ...]]:
    legacy_valuation = (*make_analytic_valuation_cases(), *make_real_valuation_cases(seed))
    valuation = (
        *legacy_valuation,
        *make_valuation_axiom_cases(),
        *make_valuation_corruption_cases(seed),
        *make_valuation_contribution_cases(seed),
        *make_valuation_noise_cases(seed),
        *make_valuation_structural_cases(seed),
        *make_valuation_replication_cases(seed),
    )
    procurement = (
        *make_procurement_cases(legacy_valuation, seed=seed),
        *make_procurement_additive_cases(seed),
        *make_procurement_submodular_cases(seed),
        *make_procurement_ml_cases(seed),
        *make_procurement_concentration_cases(seed),
    )
    trading = (
        *make_trade_cases(seed=seed),
        *make_bilateral_trade_cases(seed),
        *make_double_auction_cases(seed),
        *make_no_trade_cases(seed),
        *make_correlated_trade_cases(seed),
        *make_market_thickness_cases(seed),
    )
    return {
        "valuation": tuple(valuation),
        "procurement": tuple(procurement),
        "trading": tuple(trading),
    }


def methods_for_case(
    config: BenchmarkConfig,
    registry: MethodRegistry,
    track: str,
    case_type: str,
) -> dict[str, Mapping[str, Any]]:
    configured = dict(config.methods.get(track, {}))
    expand_all = configured.pop("all_compatible", None) is not None
    if not expand_all:
        return configured
    expanded = {spec.method_id: {} for spec in registry.compatible(track, case_type)}
    expanded.update(configured)
    return dict(sorted(expanded.items()))


def _run_id(config: BenchmarkConfig, track: str, method_id: str, case_id: str, seed: int) -> str:
    payload = f"{config.name}|{track}|{method_id}|{case_id}|{seed}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def _case_seeds(config: BenchmarkConfig, spec, case) -> tuple[int, ...]:
    if not spec.stochastic:
        return (config.seeds[0],)
    return config.seeds


@dataclass
class _RunRecord:
    run_id: str
    track: str
    method_id: str
    case: Any
    seed: int
    spec: Any
    method: Any
    status: str
    runtime: float
    output: Any = None
    error: str | None = None


def run_benchmark(
    config: BenchmarkConfig,
    *,
    registry: MethodRegistry | None = None,
    cases: Mapping[str, tuple[Any, ...]] | None = None,
) -> tuple[BenchmarkResult, ...]:
    registry = registry or build_registry()
    case_catalog = dict(cases or build_cases())
    provenance = load_provenance()
    records: list[_RunRecord] = []

    for track in TRACKS:
        wanted_cases = set(config.case_ids.get(track, ()))
        selected_cases = [
            case
            for case in case_catalog.get(track, ())
            if not wanted_cases or case.case_id in wanted_cases
        ]
        # An explicit empty case list disables a track.
        if track in config.case_ids and not config.case_ids[track]:
            selected_cases = []
        for case in selected_cases:
            for method_id, params in methods_for_case(
                config, registry, track, case.case_type
            ).items():
                method = registry.create(method_id, params)
                spec = method.spec
                if spec.track != track or (
                    case.case_type not in spec.supported_case_types
                ):
                    continue
                for seed in _case_seeds(config, spec, case):
                    run_id = _run_id(config, track, method_id, case.case_id, seed)
                    started = time.perf_counter()
                    try:
                        if track == "valuation":
                            output = method.evaluate(case, seed)
                            public_case = case
                        elif track == "procurement":
                            output = method.allocate(case.public, seed)
                            public_case = case.public
                        else:
                            output = method.clear(case.public, seed)
                            public_case = case.public
                        validate_output(spec, public_case, output)
                    except OptionalMethodUnavailable as exc:
                        records.append(
                            _RunRecord(
                                run_id,
                                track,
                                method_id,
                                case,
                                seed,
                                spec,
                                method,
                                "skipped",
                                time.perf_counter() - started,
                                error=exc.reason,
                            )
                        )
                    except Exception as exc:  # retained as a benchmark result by design
                        records.append(
                            _RunRecord(
                                run_id,
                                track,
                                method_id,
                                case,
                                seed,
                                spec,
                                method,
                                "failed",
                                time.perf_counter() - started,
                                error=f"{type(exc).__name__}: {exc}",
                            )
                        )
                    else:
                        records.append(
                            _RunRecord(
                                run_id,
                                track,
                                method_id,
                                case,
                                seed,
                                spec,
                                method,
                                "completed",
                                time.perf_counter() - started,
                                output=output,
                            )
                        )

    completed = [record for record in records if record.status == "completed"]

    def oracle_for(record: _RunRecord):
        exact = [
            candidate
            for candidate in completed
            if candidate.track == record.track
            and candidate.case.case_id == record.case.case_id
            and candidate.spec.role == "oracle"
            and candidate.seed == record.seed
        ]
        if exact:
            return exact[0].output
        fallback = [
            candidate
            for candidate in completed
            if candidate.track == record.track
            and candidate.case.case_id == record.case.case_id
            and candidate.spec.role == "oracle"
        ]
        return fallback[0].output if fallback else None

    results = []
    for record in records:
        source_record = provenance.mechanisms.get(record.method_id)
        if record.status != "completed":
            metrics = {}
        elif record.track == "valuation":
            peers: list[object] = [
                candidate.output
                for candidate in completed
                if candidate is not record
                and candidate.track == "valuation"
                and candidate.method_id == record.method_id
                and candidate.case.case_id == record.case.case_id
            ]
            if record.case.metadata.get("duplicate_pair"):
                peers.extend(
                    (candidate.case, candidate.output)
                    for candidate in completed
                    if candidate.track == "valuation"
                    and candidate.method_id == record.method_id
                    and candidate.case.case_id == "C-real-clean"
                    and candidate.seed == record.seed
                )
            replication_baseline = record.case.metadata.get(
                "replication_baseline_case_id"
            )
            if replication_baseline and record.case.case_id != replication_baseline:
                peers.extend(
                    (candidate.case, candidate.output)
                    for candidate in completed
                    if candidate.track == "valuation"
                    and candidate.method_id == record.method_id
                    and candidate.case.case_id == replication_baseline
                    and candidate.seed == record.seed
                )
            metrics = evaluate_valuation_metrics(
                record.case,
                record.output,
                oracle_output=oracle_for(record),
                peer_outputs=peers,
            )
        elif record.track == "procurement":
            metrics = evaluate_procurement_metrics(
                record.case,
                record.output,
                record.spec,
                oracle_for(record),
                method=record.method if config.strategic_audit else None,
                seed=record.seed,
            )
        else:
            metrics = evaluate_trading_metrics(
                record.case,
                record.output,
                record.spec,
                oracle_for(record),
                method=record.method if config.strategic_audit else None,
                seed=record.seed,
            )
        if config.result_metric_ids is not None:
            allowed_metrics = frozenset(
                config.result_metric_ids.get(record.track, ())
            )
            metrics = {
                metric_id: metric
                for metric_id, metric in metrics.items()
                if metric_id in allowed_metrics
            }
        diagnostic_keys = (
            (
                "mechanism_branch",
                "utility_query_count",
                "suffix_truncated",
            )
            if config.result_diagnostic_keys is None
            else config.result_diagnostic_keys
        )
        results.append(
            BenchmarkResult(
                run_id=record.run_id,
                track=record.track,
                method_id=record.method_id,
                case_id=record.case.case_id,
                seed=record.seed,
                status=record.status,
                metrics=metrics,
                runtime_seconds=record.runtime,
                error=record.error,
                outcome=(
                    serialize_outcome(record.track, record.output)
                    if record.status == "completed"
                    else None
                ),
                metadata={
                    "method_role": record.spec.role,
                    "method_source": record.spec.source,
                    "method_family": record.spec.family_id,
                    "method_capabilities": sorted(record.spec.capabilities),
                    "implementation_kind": record.spec.implementation_kind,
                    "provenance_kind": (
                        source_record.provenance_kind
                        if source_record is not None
                        else record.spec.provenance_kind
                    ),
                    "reference_keys": list(
                        source_record.reference_keys
                        if source_record is not None
                        else record.spec.reference_keys
                    ),
                    "algorithm_location": (
                        source_record.algorithm_location
                        if source_record is not None
                        else record.spec.algorithm_location
                    ),
                    "deviations": list(
                        source_record.deviations
                        if source_record is not None
                        else record.spec.deviations
                    ),
                    "metric_catalog_version": "1.2",
                    "case_assumptions": list(record.case.metadata.get("assumptions", ())),
                    "case_type": record.case.case_type,
                    **(
                        {
                            key: record.output.diagnostics[key]
                            for key in diagnostic_keys
                            if key in record.output.diagnostics
                        }
                        if record.output is not None
                        else {}
                    ),
                    **{
                        key: record.case.metadata[key]
                        for key in (
                            "benchmark_setting",
                            "cohort",
                            "evidence_scope",
                            "independent_block",
                            "source_id",
                            "pilot",
                            "property",
                            "regime",
                            "source_case_id",
                            "budget_ratio",
                            "dataset_id",
                            "dataset_name",
                            "replicated_owner",
                            "replication_factor",
                            "replication_baseline_case_id",
                            "replication_group_id",
                            "replication_mode",
                            "concentration_level",
                            "largest_singleton_share",
                            "budget_item_count",
                            "efficient_trade_count",
                            "market_size",
                            "thickness_axis",
                            "surplus_margin_profile",
                            "minimum_efficient_surplus",
                            "primary_metric_eligible",
                        )
                        if key in record.case.metadata
                    },
                },
                schema_version="1.2",
            )
        )
    return tuple(results)


__all__ = [
    "BenchmarkConfig",
    "build_cases",
    "build_registry",
    "load_config",
    "methods_for_case",
    "run_benchmark",
]
