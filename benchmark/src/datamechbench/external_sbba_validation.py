"""Cross-check SBBA against the pinned author-maintained SBB generalization."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
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
DEFAULT_FIXTURES = DEFAULT_EXTERNAL_DIRECTORY / "sbba_fixtures.json"
DEFAULT_OUTPUT_DIRECTORY = PACKAGE_ROOT / "evidence"

VALIDATION_ID = "erelsgl-auctions-sbba-specialization-d1a55eaa"
UPSTREAM_COMMIT = "d1a55eaacb337ecebeaf5f57a67bcd6a9d4411eb"
UPSTREAM_REPOSITORY = "https://github.com/erelsgl/auctions"
UPSTREAM_SOURCE_URL = (
    f"{UPSTREAM_REPOSITORY}/blob/{UPSTREAM_COMMIT}/trade_reduction_protocol.py"
)
UPSTREAM_ARCHIVE_SHA256 = (
    "d44b31327155c4a226ebef65548c9be053b10914f98bddd0233b237aed51ac6b"
)
COMPARISON_TOLERANCE = 1e-12
MAX_SUPPORT_SEED = 4096

SOURCE_FILES: Mapping[str, tuple[str, str]] = {
    "external_source": (
        "trade_reduction_protocol.py",
        "54d73de744842c960302fc7eddd6e94241a1ecb3a6ae0f0270ab2ffe50c440ea",
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
BRANCH_CODES = {
    "no_trade": 0.0,
    "full_trade": 1.0,
    "seller_lottery_trade_reduction": 2.0,
}


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
    module_names = ("agents", "trade", "markets", "trade_reduction_protocol")
    previous = {name: sys.modules.get(name) for name in module_names}
    try:
        agents = _load_source_module("agents", external_directory / "agents.py")
        _load_source_module("trade", external_directory / "trade.py")
        markets = _load_source_module("markets", external_directory / "markets.py")
        protocol = _load_source_module(
            "trade_reduction_protocol",
            external_directory / "trade_reduction_protocol.py",
        )
    finally:
        for name, original in previous.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original
    return (
        agents.AgentCategory,
        markets.Market,
        protocol.budget_balanced_trade_reduction,
    )


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


def _realized_gft(case: TradeInput, outcome: MarketOutcome) -> Decimal:
    return sum(
        (
            case.bids[allocation.actor_id]
            - case.asks[str(allocation.counterparty_id)]
            for allocation in outcome.allocations
        ),
        Decimal("0"),
    )


def _local_observables(raw_case: Mapping[str, Any]) -> tuple[str, list[float]]:
    case = _trade_input(raw_case)
    method = build_registry().create("sbba")
    first = method.clear(case, seed=0)
    branch = str(first.diagnostics.get("branch", "no_trade"))
    if branch not in BRANCH_CODES:
        raise ValueError(f"unsupported local SBBA branch: {branch}")
    trade_count = len(first.allocations)
    price = float(first.diagnostics.get("uniform_price", 0))
    strong_balance = float(bool(first.diagnostics.get("strong_budget_balance", True)))
    randomized_seller = branch == "seller_lottery_trade_reduction"
    if randomized_seller:
        efficient_count = int(first.diagnostics["efficient_trade_count"])
        ranked_sellers = sorted(
            case.seller_ids, key=lambda seller: (case.asks[seller], seller)
        )
        expected_support = set(ranked_sellers[:efficient_count])
        support_gft: dict[str, Decimal] = {}
        for seed in range(MAX_SUPPORT_SEED):
            outcome = method.clear(case, seed=seed)
            if (
                str(outcome.diagnostics.get("branch")) != branch
                or len(outcome.allocations) != trade_count
                or float(outcome.diagnostics.get("uniform_price", 0)) != price
            ):
                raise ValueError("local SBBA stochastic branch is not structurally stable")
            excluded = str(outcome.diagnostics.get("excluded_seller", ""))
            if excluded not in expected_support:
                raise ValueError("local SBBA seller lottery left its efficient support")
            support_gft.setdefault(excluded, _realized_gft(case, outcome))
            if set(support_gft) == expected_support:
                break
        if set(support_gft) != expected_support:
            raise ValueError("local SBBA seller lottery support was not fully observed")
        expected_gft = sum(support_gft.values(), Decimal("0")) / Decimal(
            len(support_gft)
        )
        buyer_candidate_count = trade_count
        seller_candidate_count = len(support_gft)
    else:
        expected_gft = _realized_gft(case, first)
        buyer_candidate_count = trade_count
        seller_candidate_count = trade_count
    return branch, [
        float(trade_count),
        price,
        float(buyer_candidate_count),
        float(seller_candidate_count),
        0.0,
        float(randomized_seller),
        float(expected_gft),
        strong_balance,
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
    trade = mechanism(market, [1, 1])
    trade_count = int(trade.num_of_deals())
    buyer_candidates = len(trade.categories[0].values)
    seller_candidates = len(trade.categories[1].values)
    randomized_buyer = buyer_candidates > trade_count
    randomized_seller = seller_candidates > trade_count
    if trade_count == 0:
        branch = "no_trade"
        price = 0.0
        randomized_buyer = randomized_seller = False
    elif randomized_seller and not randomized_buyer:
        branch = "seller_lottery_trade_reduction"
        price = float(trade.prices[0])
    elif not randomized_buyer and not randomized_seller:
        branch = "full_trade"
        price = float(trade.prices[0])
    else:
        raise ValueError("upstream specialization randomized an unsupported side")
    if trade_count == 0:
        strong_balance = True
    else:
        strong_balance = math.isclose(
            float(sum(trade.prices)), 0.0, rel_tol=0.0, abs_tol=COMPARISON_TOLERANCE
        )
    return branch, [
        float(trade_count),
        price,
        float(buyer_candidates),
        float(seller_candidates),
        float(randomized_buyer),
        float(randomized_seller),
        float(trade.gain_from_trade(including_auctioneer=True)),
        float(strong_balance),
        BRANCH_CODES[branch],
    ]


def _scores(raw: Any) -> list[float]:
    if not isinstance(raw, list):
        raise ValueError("fixture score vector must be a list")
    return [float(value) for value in raw]


def _maximum_error(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("fixture score vectors must have the same nonzero length")
    return max(abs(a - b) for a, b in zip(left, right, strict=True))


def _compare_case(
    raw_case: Any,
    observable_names: list[str],
    agent_category: type[Any],
    market_class: type[Any],
    mechanism: Any,
) -> dict[str, Any]:
    if not isinstance(raw_case, Mapping):
        raise ValueError("SBBA cross-check case must be an object")
    local_branch, local_scores = _local_observables(raw_case)
    external_branch, external_scores = _external_observables(
        raw_case, agent_category, market_class, mechanism
    )
    expected_branch = str(raw_case["expected_branch"])
    expected_scores = _scores(raw_case["expected_scores"])
    if len(expected_scores) != len(observable_names):
        raise ValueError("fixture expected score count differs from observables")
    implementation_error = _maximum_error(local_scores, external_scores)
    oracle_error = max(
        _maximum_error(local_scores, expected_scores),
        _maximum_error(external_scores, expected_scores),
    )
    branch_match = local_branch == external_branch == expected_branch
    if (
        implementation_error > COMPARISON_TOLERANCE
        or oracle_error > COMPARISON_TOLERANCE
        or not branch_match
    ):
        raise ValueError(
            f"validated-domain fixture {raw_case.get('case_id', '<missing>')} disagrees"
        )
    return {
        "case_id": str(raw_case["case_id"]),
        "branch": expected_branch,
        "local_branch": local_branch,
        "external_branch": external_branch,
        "branch_match": branch_match,
        "observable_names": observable_names,
        "local_scores": local_scores,
        "external_scores": external_scores,
        "expected_scores": expected_scores,
        "maximum_absolute_error": implementation_error,
        "maximum_fixture_oracle_error": oracle_error,
    }


def _compare_boundary_case(
    raw_case: Any,
    observable_names: list[str],
    agent_category: type[Any],
    market_class: type[Any],
    mechanism: Any,
) -> dict[str, Any]:
    if not isinstance(raw_case, Mapping):
        raise ValueError("SBBA boundary case must be an object")
    local_branch, local_scores = _local_observables(raw_case)
    external_branch, external_scores = _external_observables(
        raw_case, agent_category, market_class, mechanism
    )
    expected_local = _scores(raw_case["expected_local_scores"])
    expected_external = _scores(raw_case["expected_external_scores"])
    if len(expected_local) != len(observable_names) or len(expected_external) != len(
        observable_names
    ):
        raise ValueError("boundary fixture score count differs from observables")
    local_oracle_error = _maximum_error(local_scores, expected_local)
    external_oracle_error = _maximum_error(external_scores, expected_external)
    matches = (
        local_branch == str(raw_case["expected_local_branch"])
        and external_branch == str(raw_case["expected_external_branch"])
        and local_oracle_error <= COMPARISON_TOLERANCE
        and external_oracle_error <= COMPARISON_TOLERANCE
        and _maximum_error(local_scores, external_scores) > COMPARISON_TOLERANCE
    )
    if not matches:
        raise ValueError("declared SBBA semantic boundary no longer matches evidence")
    return {
        "case_id": str(raw_case["case_id"]),
        "boundary_id": str(raw_case["boundary_id"]),
        "status": "expected_semantic_boundary",
        "reason": (
            "the generalized code requires strictly positive external competition; "
            "the two-sided SBBA equality case retains full trade"
        ),
        "observable_names": observable_names,
        "local_branch": local_branch,
        "external_branch": external_branch,
        "local_scores": local_scores,
        "external_scores": external_scores,
        "expected_local_scores": expected_local,
        "expected_external_scores": expected_external,
        "local_fixture_oracle_error": local_oracle_error,
        "external_fixture_oracle_error": external_oracle_error,
        "maximum_absolute_difference": _maximum_error(
            local_scores, external_scores
        ),
        "matches_declared_difference": matches,
    }


def _binding(role: str, path: Path, root: Path) -> dict[str, Any]:
    return {
        "role": role,
        "path": _repository_relative(path, root, role),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
    }


def build_official_sbba_validation(
    *,
    external_directory: str | Path = DEFAULT_EXTERNAL_DIRECTORY,
    fixture_path: str | Path = DEFAULT_FIXTURES,
    runner_path: str | Path,
    output_directory: str | Path = DEFAULT_OUTPUT_DIRECTORY,
    repository_root: str | Path = REPOSITORY_ROOT,
) -> dict[str, Any]:
    """Execute the local rule and pinned upstream two-category specialization."""

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
            raise ValueError(f"pinned SBBA upstream {name} hash mismatch")
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
    ) != "sbba_official_generalization_specialization_crosscheck":
        raise ValueError("invalid external SBBA fixture schema")
    observable_names = [str(value) for value in fixtures.get("observable_names", [])]
    cases = fixtures.get("cases")
    boundary_cases = fixtures.get("boundary_cases")
    if not observable_names or not isinstance(cases, list) or len(cases) < 5:
        raise ValueError("external SBBA cross-check requires five generic fixtures")
    if not isinstance(boundary_cases, list) or len(boundary_cases) != 1:
        raise ValueError("external SBBA cross-check requires one boundary fixture")

    agent_category, market_class, mechanism = _load_upstream(external)
    comparisons = [
        _compare_case(
            case, observable_names, agent_category, market_class, mechanism
        )
        for case in cases
    ]
    boundaries = [
        _compare_boundary_case(
            case, observable_names, agent_category, market_class, mechanism
        )
        for case in boundary_cases
    ]
    maximum_error = max(
        float(item["maximum_absolute_error"]) for item in comparisons
    )
    maximum_oracle_error = max(
        float(item["maximum_fixture_oracle_error"]) for item in comparisons
    )
    executed_sources = {
        role: _sha256(path) for role, path in source_paths.items()
    }
    result = {
        "schema_version": "1.0",
        "result_kind": "external_implementation_comparison",
        "validation_id": VALIDATION_ID,
        "method_id": "sbba",
        "external_commit": UPSTREAM_COMMIT,
        "executed_source_sha256": executed_sources["external_source"],
        "executed_source_files": executed_sources,
        "upstream_archive_sha256": UPSTREAM_ARCHIVE_SHA256,
        "source_execution": (
            "upstream_files_with_declared_terminal_newline_normalization"
        ),
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
        "all_close": True,
        "maximum_absolute_error": maximum_error,
        "maximum_fixture_oracle_error": maximum_oracle_error,
        "fixture_count": len(comparisons),
        "boundary_fixture_count": len(boundaries),
        "comparisons": comparisons,
        "boundary_comparisons": boundaries,
    }
    output.mkdir(parents=True, exist_ok=True)
    result_path = output / "external_erelsgl_sbba_results_v1.json"
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
        "method_id": "sbba",
        "track": "trading",
        "claim_boundary": (
            "general-position two-category [1,1] specialization: branch, trade "
            "count, uniform price, candidate support, randomized side, expected "
            "gain from trade, and strong budget balance; no identity-level random "
            "draw parity; zero-external-competition tie disclosed separately"
        ),
        "external_implementation": {
            "name": (
                "Erel Segal-Halevi auctions SBB external-competition protocol, "
                "two-category recipe specialization"
            ),
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
    record_path = output / "external_erelsgl_sbba_v1.json"
    record_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


__all__ = [
    "DEFAULT_EXTERNAL_DIRECTORY",
    "DEFAULT_FIXTURES",
    "DEFAULT_OUTPUT_DIRECTORY",
    "REPOSITORY_ROOT",
    "build_official_sbba_validation",
]
