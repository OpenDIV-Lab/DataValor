from __future__ import annotations

from datamechbench.catalog import catalog_summary, load_catalog
from datamechbench.data import make_analytic_valuation_cases
from datamechbench.models import MethodSpec, ValuationOutput
from datamechbench.registry import MethodRegistry
from datamechbench.runner import BenchmarkConfig, build_registry, methods_for_case, run_benchmark


class _Constant:
    def __init__(self, spec: MethodSpec) -> None:
        self.spec = spec

    def evaluate(self, case, seed):
        del seed
        return ValuationOutput({owner: 1.0 for owner in case.owner_ids})


def _spec(method_id: str, family_id: str, supported: frozenset[str]) -> MethodSpec:
    return MethodSpec(
        method_id=method_id,
        family_id=family_id,
        track="valuation",
        role="method",
        source="test",
        version="1",
        implementation_kind="native",
        supported_case_types=supported,
    )


def test_family_counts_deduplicate_adapters_and_profiles():
    registry = MethodRegistry()
    for method_id, kind in (("tmc_native", "native"), ("tmc_pydvl", "external_adapter")):
        spec = MethodSpec(
            method_id=method_id,
            family_id="tmc_shapley",
            track="valuation",
            role="method",
            source="test",
            version="1",
            implementation_kind=kind,
            supported_case_types=frozenset({"analytic"}),
        )
        registry.register(spec, lambda params, spec=spec: _Constant(spec))

    summary = catalog_summary(registry, {"valuation": ()})

    assert summary["tracks"]["valuation"]["method_count"] == 2
    assert summary["tracks"]["valuation"]["family_count"] == 1
    assert summary["tracks"]["valuation"]["native_family_count"] == 1


def test_empty_supported_case_types_is_explicitly_incompatible():
    registry = MethodRegistry()
    supported = _spec("supported", "supported", frozenset({"analytic"}))
    unsupported = _spec("unsupported", "unsupported", frozenset())
    registry.register(supported, lambda params: _Constant(supported))
    registry.register(unsupported, lambda params: _Constant(unsupported))

    assert [item.method_id for item in registry.compatible("valuation", "analytic")] == [
        "supported"
    ]
    assert registry.compatible("valuation", "real_owner_data") == ()


def test_repository_catalog_has_complete_provenance():
    entries = load_catalog()
    registry = build_registry()

    assert entries
    for method_id, entry in entries.items():
        assert entry["family_id"]
        assert entry["track"] in {"valuation", "procurement", "trading"}
        assert entry["source"]
        assert entry["reference_url"].startswith("http")
        assert entry["implementation_kind"] in {"native", "external_adapter"}
        assert entry["supported_case_types"]
        assert method_id == entry["method_id"]
    assert set(entries) == {spec.method_id for spec in registry.specs()}
    for spec in registry.specs():
        entry = entries[spec.method_id]
        assert entry["family_id"] == spec.family_id
        assert entry["implementation_kind"] == spec.implementation_kind
        assert set(entry["supported_case_types"]) == set(spec.supported_case_types)


def test_all_compatible_expands_every_supported_method():
    analytic_case = make_analytic_valuation_cases()[0]
    registry = MethodRegistry()
    for method_id in ("a", "b"):
        spec = _spec(method_id, method_id, frozenset({"analytic"}))
        registry.register(spec, lambda params, spec=spec: _Constant(spec))
    other = _spec("other", "other", frozenset({"real_owner_data"}))
    registry.register(other, lambda params: _Constant(other))
    config = BenchmarkConfig(
        name="expand",
        output_dir="unused",
        seeds=(0,),
        methods={"valuation": {"all_compatible": {}}, "procurement": {}, "trading": {}},
        case_ids={"valuation": (analytic_case.case_id,), "procurement": (), "trading": ()},
        strategic_audit=False,
    )

    expanded = methods_for_case(config, registry, "valuation", "analytic")
    results = run_benchmark(
        config,
        registry=registry,
        cases={"valuation": (analytic_case,), "procurement": (), "trading": ()},
    )

    assert tuple(expanded) == ("a", "b")
    assert [result.method_id for result in results] == ["a", "b"]
