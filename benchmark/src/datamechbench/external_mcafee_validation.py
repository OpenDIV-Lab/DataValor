"""Cross-check McAfee against Erel Segal-Halevi's pinned official source."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import platform
import sys
import types
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from .models import MarketOutcome, TradeInput
from .runner import build_registry

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = PACKAGE_ROOT.parent
DEFAULT_EXTERNAL_DIRECTORY = PACKAGE_ROOT / "external" / "erelsgl_auctions"
DEFAULT_FIXTURES = DEFAULT_EXTERNAL_DIRECTORY / "mcafee_fixtures.json"
DEFAULT_TRADE_REDUCTION_FIXTURES = (
    DEFAULT_EXTERNAL_DIRECTORY / "trade_reduction_fixtures.json"
)
DEFAULT_OUTPUT_DIRECTORY = PACKAGE_ROOT / "evidence"

VALIDATION_ID = "erelsgl-auctions-mcafee-d1a55eaa"
TRADE_REDUCTION_VALIDATION_ID = "erelsgl-auctions-trade-reduction-d1a55eaa"
UPSTREAM_COMMIT = "d1a55eaacb337ecebeaf5f57a67bcd6a9d4411eb"
UPSTREAM_REPOSITORY = "https://github.com/erelsgl/auctions"
UPSTREAM_SOURCE_URL = (
    f"{UPSTREAM_REPOSITORY}/blob/{UPSTREAM_COMMIT}/mcafee_protocol.py"
)
UPSTREAM_ARCHIVE_SHA256 = (
    "d44b31327155c4a226ebef65548c9be053b10914f98bddd0233b237aed51ac6b"
)
COMPARISON_TOLERANCE = 1e-12

SOURCE_FILES: Mapping[str, tuple[str, str]] = {
    "external_source": (
        "mcafee_protocol.py",
        "4f084fcb1aa17a5e5f51c97f528d75969983c789caf82bcdbca76e233f9c49ef",
    ),
    "external_dependency_agents": (
        "agents.py",
        "59ec8cdb818c79a56916c075dee00c21da29475179eec917ae2007ddb1b4d6b2",
    ),
    "external_dependency_markets": (
        "markets.py",
        "16ef56d2dd86fba0357f7b05d9651fac72557b61aa4aba123f44cd250a2bea54",
    ),
    "external_dependency_trade": (
        "trade.py",
        "851e2253d0bf9c2aecbb99fbaf44c4dc87c242d9123c68fd73ab0df239456ef4",
    ),
}
UPSTREAM_TRADE_SOURCE_SHA256 = (
    "41c23c1008d84c4bd8fce9d7bf6d8e7c68005c65187466ed84a32b820d53873f"
)
LICENSE_SHA256 = "b7c6d729e5646327fb2c69913e5daca0059014a86d6d1ea809a0409af68135ea"
BRANCH_CODES = {"no_trade": 0.0, "candidate_price": 1.0, "trade_reduction": 2.0}


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
        raise ValueError(f"{label} must be inside repository root") from exc
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{label} must be a regular non-symlink file")
    return relative.as_posix()


def _load_source_module(name: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"unable to load pinned upstream module: {name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_upstream(external_directory: Path) -> tuple[type[Any], type[Any], Any]:
    """Execute the pinned modules under their unchanged upstream import names."""

    module_names = ("agents", "trade", "markets", "mcafee_protocol")
    previous = {name: sys.modules.get(name) for name in module_names}
    try:
        agents = _load_source_module("agents", external_directory / "agents.py")
        _load_source_module("trade", external_directory / "trade.py")
        markets = _load_source_module("markets", external_directory / "markets.py")
        protocol = _load_source_module(
            "mcafee_protocol", external_directory / "mcafee_protocol.py"
        )
    finally:
        for name, original in previous.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original
    return agents.AgentCategory, markets.Market, protocol.mcafee_trade_reduction


def _trade_input(raw_case: Mapping[str, Any]) -> TradeInput:
    bids = tuple(Decimal(str(value)) for value in raw_case["bids"])
    asks = tuple(Decimal(str(value)) for value in raw_case["asks"])
    buyer_ids = tuple(f"b{index + 1}" for index in range(len(bids)))
    seller_ids = tuple(f"s{index + 1}" for index in range(len(asks)))
    return TradeInput(
        product_id="data-access",
        buyer_ids=buyer_ids,
        seller_ids=seller_ids,
        bids=dict(zip(buyer_ids, bids, strict=True)),
        asks=dict(zip(seller_ids, asks, strict=True)),
    )


def _local_observables(case: TradeInput, outcome: MarketOutcome) -> tuple[str, list[float]]:
    branch = str(outcome.diagnostics.get("branch", "no_trade"))
    trade_count = len(outcome.allocations)
    if trade_count:
        buyer_price = float(outcome.diagnostics["buyer_price"])
        seller_receipt = float(outcome.diagnostics["seller_price"])
    else:
        buyer_price = seller_receipt = 0.0
    gain = sum(
        case.bids[allocation.actor_id] - case.asks[str(allocation.counterparty_id)]
        for allocation in outcome.allocations
    )
    surplus = Decimal(str(outcome.diagnostics.get("auctioneer_surplus", "0")))
    return branch, [
        float(trade_count),
        buyer_price,
        seller_receipt,
        float(gain),
        float(surplus),
        BRANCH_CODES[branch],
    ]


def _external_observables(
    raw_case: Mapping[str, Any],
    agent_category: type[Any],
    market_class: type[Any],
    mechanism: Any,
) -> tuple[str, list[float]]:
    bids = [float(value) for value in raw_case["bids"]]
    asks = [float(value) for value in raw_case["asks"]]
    market = market_class([
        agent_category("buyer", bids),
        agent_category("seller", [-value for value in asks]),
    ])
    trade = mechanism(market, [1, 1], price_heuristic=True)
    trade_count = int(trade.num_of_deals())
    efficient_count = sum(
        bid >= ask
        for bid, ask in zip(sorted(bids, reverse=True), sorted(asks), strict=False)
    )
    if trade_count == 0:
        branch = "no_trade"
        buyer_price = seller_receipt = 0.0
    else:
        buyer_price = float(trade.prices[0])
        seller_receipt = -float(trade.prices[1])
        branch = (
            "candidate_price"
            if trade_count == efficient_count and buyer_price == seller_receipt
            else "trade_reduction"
        )
    gain = float(trade.gain_from_trade(including_auctioneer=True))
    trader_gain = float(trade.gain_from_trade(including_auctioneer=False))
    return branch, [
        float(trade_count),
        buyer_price,
        seller_receipt,
        gain,
        gain - trader_gain,
        BRANCH_CODES[branch],
    ]


def _compare_case(
    raw_case: Any,
    observable_names: list[str],
    agent_category: type[Any],
    market_class: type[Any],
    mechanism: Any,
) -> dict[str, Any]:
    if not isinstance(raw_case, Mapping):
        raise ValueError("McAfee cross-check case must be an object")
    case = _trade_input(raw_case)
    local = build_registry().create("mcafee").clear(case, seed=0)
    local_branch, local_scores = _local_observables(case, local)
    external_branch, external_scores = _external_observables(
        raw_case, agent_category, market_class, mechanism
    )
    expected_branch = str(raw_case["expected_branch"])
    expected_scores = [float(value) for value in raw_case["expected_scores"]]
    if len(expected_scores) != len(observable_names):
        raise ValueError("fixture expected score count differs from observables")
    maximum_error = max(
        abs(local_value - external_value)
        for local_value, external_value in zip(
            local_scores, external_scores, strict=True
        )
    )
    oracle_error = max(
        abs(observed - expected)
        for scores in (local_scores, external_scores)
        for observed, expected in zip(scores, expected_scores, strict=True)
    )
    return {
        "case_id": str(raw_case["case_id"]),
        "branch": expected_branch,
        "local_branch": local_branch,
        "external_branch": external_branch,
        "branch_match": local_branch == external_branch == expected_branch,
        "observable_names": observable_names,
        "local_scores": local_scores,
        "external_scores": external_scores,
        "expected_scores": expected_scores,
        "maximum_absolute_error": maximum_error,
        "maximum_fixture_oracle_error": oracle_error,
    }


def _standalone_trade_reduction_observables(
    case: TradeInput, outcome: MarketOutcome
) -> tuple[str, list[float]]:
    trade_count = len(outcome.allocations)
    diagnostics = outcome.diagnostics
    if trade_count == 0:
        branch = "no_trade"
        buyer_price = seller_receipt = 0.0
    else:
        branch = "trade_reduction"
        buyer_price = float(diagnostics["buyer_price"])
        seller_receipt = float(diagnostics["seller_price"])
    gain = sum(
        case.bids[allocation.actor_id]
        - case.asks[str(allocation.counterparty_id)]
        for allocation in outcome.allocations
    )
    surplus = Decimal(str(diagnostics.get("auctioneer_surplus", "0")))
    return branch, [
        float(trade_count),
        buyer_price,
        seller_receipt,
        float(gain),
        float(surplus),
        BRANCH_CODES[branch],
    ]


def _compare_trade_reduction_case(
    raw_case: Any,
    observable_names: list[str],
    agent_category: type[Any],
    market_class: type[Any],
    mechanism: Any,
) -> dict[str, Any]:
    if not isinstance(raw_case, Mapping):
        raise ValueError("Trade Reduction cross-check case must be an object")
    case = _trade_input(raw_case)
    local = build_registry().create("trade_reduction").clear(case, seed=0)
    local_branch, local_scores = _standalone_trade_reduction_observables(
        case, local
    )
    external_branch, external_scores = _external_observables(
        raw_case, agent_category, market_class, mechanism
    )
    expected_branch = str(raw_case["expected_branch"])
    expected_scores = [float(value) for value in raw_case["expected_scores"]]
    if len(expected_scores) != len(observable_names):
        raise ValueError("fixture expected score count differs from observables")
    maximum_error = max(
        abs(local_value - external_value)
        for local_value, external_value in zip(
            local_scores, external_scores, strict=True
        )
    )
    oracle_error = max(
        abs(observed - expected)
        for scores in (local_scores, external_scores)
        for observed, expected in zip(scores, expected_scores, strict=True)
    )
    return {
        "case_id": str(raw_case["case_id"]),
        "branch": expected_branch,
        "local_branch": local_branch,
        "external_branch": external_branch,
        "branch_match": local_branch == external_branch == expected_branch,
        "observable_names": observable_names,
        "local_scores": local_scores,
        "external_scores": external_scores,
        "expected_scores": expected_scores,
        "maximum_absolute_error": maximum_error,
        "maximum_fixture_oracle_error": oracle_error,
    }


def _binding(role: str, path: Path, root: Path) -> dict[str, Any]:
    return {
        "role": role,
        "path": _repository_relative(path, root, role),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
    }


def build_official_mcafee_validation(
    *,
    external_directory: str | Path = DEFAULT_EXTERNAL_DIRECTORY,
    fixture_path: str | Path = DEFAULT_FIXTURES,
    runner_path: str | Path,
    output_directory: str | Path = DEFAULT_OUTPUT_DIRECTORY,
    repository_root: str | Path = REPOSITORY_ROOT,
) -> dict[str, Any]:
    """Execute both implementations and write byte-bound comparison evidence."""

    root = Path(repository_root)
    external = Path(external_directory)
    fixtures_file = Path(fixture_path)
    runner = Path(runner_path)
    output = Path(output_directory)
    source_paths: dict[str, Path] = {}
    for role, (name, expected_hash) in SOURCE_FILES.items():
        path = external / name
        _repository_relative(path, root, role)
        if _sha256(path) != expected_hash:
            raise ValueError(f"pinned McAfee {name} hash mismatch")
        source_paths[role] = path
    license_path = external / "LICENSE.txt"
    for label, path in (
        ("license", license_path),
        ("fixtures", fixtures_file),
        ("runner", runner),
    ):
        _repository_relative(path, root, label)
    if _sha256(license_path) != LICENSE_SHA256:
        raise ValueError("pinned auctions license hash mismatch")

    fixtures = json.loads(fixtures_file.read_text(encoding="utf-8"))
    if fixtures.get("schema_version") != "1.0" or fixtures.get(
        "fixture_kind"
    ) != "mcafee_official_external_crosscheck":
        raise ValueError("invalid external McAfee fixture schema")
    observable_names = [str(value) for value in fixtures.get("observable_names", [])]
    cases = fixtures.get("cases")
    if not observable_names or not isinstance(cases, list) or len(cases) < 5:
        raise ValueError("external McAfee cross-check requires five branch fixtures")

    agent_category, market_class, mechanism = _load_upstream(external)
    comparisons = [
        _compare_case(
            case, observable_names, agent_category, market_class, mechanism
        )
        for case in cases
    ]
    maximum_error = max(
        float(item["maximum_absolute_error"]) for item in comparisons
    )
    maximum_oracle_error = max(
        float(item["maximum_fixture_oracle_error"]) for item in comparisons
    )
    all_close = (
        maximum_error <= COMPARISON_TOLERANCE
        and maximum_oracle_error <= COMPARISON_TOLERANCE
        and all(bool(item["branch_match"]) for item in comparisons)
    )
    executed_sources = {
        role: _sha256(path) for role, path in source_paths.items()
    }
    result = {
        "schema_version": "1.0",
        "result_kind": "external_implementation_comparison",
        "validation_id": VALIDATION_ID,
        "method_id": "mcafee",
        "external_commit": UPSTREAM_COMMIT,
        "executed_source_sha256": executed_sources["external_source"],
        "executed_source_files": executed_sources,
        "upstream_archive_sha256": UPSTREAM_ARCHIVE_SHA256,
        "source_execution": "upstream_files_with_one_terminal_newline_normalization",
        "source_normalizations": [{
            "path": "trade.py",
            "normalization": "one terminal newline appended by text vendoring",
            "upstream_sha256": UPSTREAM_TRADE_SOURCE_SHA256,
            "executed_sha256": executed_sources["external_dependency_trade"],
            "semantic_effect": "none",
        }],
        "execution_environment": {"python": platform.python_version()},
        "semantic_alignment": fixtures["semantic_alignment"],
        "tolerance": COMPARISON_TOLERANCE,
        "all_close": all_close,
        "maximum_absolute_error": maximum_error,
        "maximum_fixture_oracle_error": maximum_oracle_error,
        "fixture_count": len(comparisons),
        "comparisons": comparisons,
    }
    output.mkdir(parents=True, exist_ok=True)
    result_path = output / "external_erelsgl_mcafee_results_v1.json"
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    artifacts = [
        *(_binding(role, path, root) for role, path in source_paths.items()),
        _binding("external_license", license_path, root),
        _binding("comparison_fixtures", fixtures_file, root),
        _binding("comparison_results", result_path, root),
        _binding("validation_runner", runner, root),
    ]
    record = {
        "schema_version": "1.0",
        "record_kind": "external_implementation_validation",
        "validation_id": VALIDATION_ID,
        "method_id": "mcafee",
        "track": "trading",
        "claim_boundary": (
            "single-unit homogeneous McAfee allocation, branch, prices, "
            "gain-from-trade, and auctioneer-surplus observables"
        ),
        "external_implementation": {
            "name": "Erel Segal-Halevi auctions McAfee trade-reduction protocol",
            "origin": "official_upstream",
            "repository_url": UPSTREAM_REPOSITORY,
            "commit_sha": UPSTREAM_COMMIT,
            "source_url": UPSTREAM_SOURCE_URL,
            "source_sha256": executed_sources["external_source"],
            "archive_sha256": UPSTREAM_ARCHIVE_SHA256,
            "license_id": "MIT",
        },
        "artifacts": artifacts,
    }
    record_path = output / "external_erelsgl_mcafee_v1.json"
    record_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def build_official_trade_reduction_validation(
    *,
    external_directory: str | Path = DEFAULT_EXTERNAL_DIRECTORY,
    fixture_path: str | Path = DEFAULT_TRADE_REDUCTION_FIXTURES,
    runner_path: str | Path,
    output_directory: str | Path = DEFAULT_OUTPUT_DIRECTORY,
    repository_root: str | Path = REPOSITORY_ROOT,
) -> dict[str, Any]:
    """Cross-check the standalone rule against McAfee's fallback branch."""

    root = Path(repository_root)
    external = Path(external_directory)
    fixtures_file = Path(fixture_path)
    runner = Path(runner_path)
    output = Path(output_directory)
    source_paths: dict[str, Path] = {}
    for role, (name, expected_hash) in SOURCE_FILES.items():
        path = external / name
        _repository_relative(path, root, role)
        if _sha256(path) != expected_hash:
            raise ValueError(f"pinned McAfee {name} hash mismatch")
        source_paths[role] = path
    license_path = external / "LICENSE.txt"
    for label, path in (
        ("license", license_path),
        ("fixtures", fixtures_file),
        ("runner", runner),
    ):
        _repository_relative(path, root, label)
    if _sha256(license_path) != LICENSE_SHA256:
        raise ValueError("pinned auctions license hash mismatch")

    fixtures = json.loads(fixtures_file.read_text(encoding="utf-8"))
    if fixtures.get("schema_version") != "1.0" or fixtures.get(
        "fixture_kind"
    ) != "mcafee_trade_reduction_fallback_external_crosscheck":
        raise ValueError("invalid external Trade Reduction fixture schema")
    observable_names = [str(value) for value in fixtures.get("observable_names", [])]
    cases = fixtures.get("cases")
    if not observable_names or not isinstance(cases, list) or len(cases) < 3:
        raise ValueError("Trade Reduction cross-check requires three fixtures")

    agent_category, market_class, mechanism = _load_upstream(external)
    comparisons = [
        _compare_trade_reduction_case(
            case, observable_names, agent_category, market_class, mechanism
        )
        for case in cases
    ]
    maximum_error = max(
        float(item["maximum_absolute_error"]) for item in comparisons
    )
    maximum_oracle_error = max(
        float(item["maximum_fixture_oracle_error"]) for item in comparisons
    )
    all_close = (
        maximum_error <= COMPARISON_TOLERANCE
        and maximum_oracle_error <= COMPARISON_TOLERANCE
        and all(bool(item["branch_match"]) for item in comparisons)
    )
    executed_sources = {
        role: _sha256(path) for role, path in source_paths.items()
    }
    result = {
        "schema_version": "1.0",
        "result_kind": "external_implementation_comparison",
        "validation_id": TRADE_REDUCTION_VALIDATION_ID,
        "method_id": "trade_reduction",
        "external_commit": UPSTREAM_COMMIT,
        "executed_source_sha256": executed_sources["external_source"],
        "executed_source_files": executed_sources,
        "upstream_archive_sha256": UPSTREAM_ARCHIVE_SHA256,
        "source_execution": "upstream_files_with_one_terminal_newline_normalization",
        "source_normalizations": [{
            "path": "trade.py",
            "normalization": "one terminal newline appended by text vendoring",
            "upstream_sha256": UPSTREAM_TRADE_SOURCE_SHA256,
            "executed_sha256": executed_sources["external_dependency_trade"],
            "semantic_effect": "none",
        }],
        "execution_environment": {"python": platform.python_version()},
        "semantic_alignment": fixtures["semantic_alignment"],
        "tolerance": COMPARISON_TOLERANCE,
        "all_close": all_close,
        "maximum_absolute_error": maximum_error,
        "maximum_fixture_oracle_error": maximum_oracle_error,
        "fixture_count": len(comparisons),
        "comparisons": comparisons,
    }
    output.mkdir(parents=True, exist_ok=True)
    result_path = output / "external_erelsgl_trade_reduction_results_v1.json"
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    artifacts = [
        *(_binding(role, path, root) for role, path in source_paths.items()),
        _binding("external_license", license_path, root),
        _binding("comparison_fixtures", fixtures_file, root),
        _binding("comparison_results", result_path, root),
        _binding("validation_runner", runner, root),
    ]
    record = {
        "schema_version": "1.0",
        "record_kind": "external_implementation_validation",
        "validation_id": TRADE_REDUCTION_VALIDATION_ID,
        "method_id": "trade_reduction",
        "track": "trading",
        "claim_boundary": (
            "homogeneous single-unit McAfee trade-reduction fallback branch: "
            "allocation count, marginal prices, gain from trade, and auctioneer "
            "surplus; no equivalence claim for the separate generalized "
            "trade_reduction_protocol.py"
        ),
        "external_implementation": {
            "name": "Erel Segal-Halevi auctions McAfee trade-reduction fallback",
            "origin": "official_upstream",
            "repository_url": UPSTREAM_REPOSITORY,
            "commit_sha": UPSTREAM_COMMIT,
            "source_url": UPSTREAM_SOURCE_URL,
            "source_sha256": executed_sources["external_source"],
            "archive_sha256": UPSTREAM_ARCHIVE_SHA256,
            "license_id": "MIT",
        },
        "artifacts": artifacts,
    }
    record_path = output / "external_erelsgl_trade_reduction_v1.json"
    record_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


__all__ = [
    "DEFAULT_EXTERNAL_DIRECTORY",
    "DEFAULT_FIXTURES",
    "DEFAULT_OUTPUT_DIRECTORY",
    "DEFAULT_TRADE_REDUCTION_FIXTURES",
    "REPOSITORY_ROOT",
    "build_official_mcafee_validation",
    "build_official_trade_reduction_validation",
]
