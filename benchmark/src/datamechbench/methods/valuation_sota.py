"""Optional adapters for maintained general-game Shapley estimators."""

from __future__ import annotations

import importlib.util
import json
import random
import subprocess
import sys
import warnings
from pathlib import Path
from typing import Any

import numpy as np

from datavalor.data_value import exact_shapley_values

from ..coalition_games import CoalitionGameTable
from ..models import ValuationOutput
from .valuation_regression_msr import run_regression_msr
from .valuation_shapley import OptionalMethodUnavailable

_SHAPIQ_CLASSES = {
    "shapiq_svarm": "SVARM",
    "shapiq_stratified_sampling": "StratifiedSamplingSV",
    "shapiq_kernel_shap": "KernelSHAP",
    "shapiq_unbiased_kernel_shap": "UnbiasedKernelSHAP",
    "shapiq_owen": "OwenSamplingSV",
    "shapiq_leverage_shap": "LeverageSHAP",
}
_OFFICIAL_SVARM_COMMIT = "c4e30395b14b8bf9a8687d839d5b406f825bb23d"


def sota_minimum_budget(method_id: str, n_players: int) -> int:
    """Return the auditable minimum coalition-call budget for a SOTA adapter."""

    if n_players < 1:
        raise ValueError("n_players must be positive")
    if method_id == "exact_table":
        return 1 << n_players
    if method_id in _SHAPIQ_CLASSES:
        return 2
    if method_id in {"official_stratified_svarm", "official_stratified_svarm_plus"}:
        return 2 * n_players + 1
    if method_id == "official_linear_regression_msr":
        return 22
    if method_id in {"pydvl_vrds", "pydvl_owen", "pydvl_group_testing"}:
        return 2
    raise KeyError(f"unsupported SOTA Shapley method: {method_id}")


def _exact(table: CoalitionGameTable) -> ValuationOutput:
    report = exact_shapley_values(
        table.owner_ids,
        lambda coalition, context: table.value(tuple(coalition)),
        max_records=len(table.owner_ids),
    )
    return ValuationOutput(
        {item.target_id: float(item.value) for item in report.contributions},
        diagnostics={
            "estimand": "ordinary_shapley",
            "logical_calls": report.utility_calls,
            "unique_coalitions": 1 << len(table.owner_ids),
            "backend": "DataValor",
            "backend_version": "native",
        },
        utility_calls=report.utility_calls,
    )


def _shapiq(
    method_id: str,
    table: CoalitionGameTable,
    *,
    budget: int,
    seed: int,
) -> ValuationOutput:
    if importlib.util.find_spec("shapiq") is None:
        raise OptionalMethodUnavailable("optional_dependency_missing:shapiq==1.7.0")
    import shapiq

    if shapiq.__version__ != "1.7.0":
        raise OptionalMethodUnavailable(
            f"unsupported_dependency_version:shapiq=={shapiq.__version__}"
        )
    if not isinstance(budget, int) or budget < 2:
        raise ValueError("budget must be an integer of at least two coalition calls")

    n_players = len(table.owner_ids)
    calls = 0
    observed_masks: set[int] = set()

    def game(coalitions: np.ndarray) -> np.ndarray:
        nonlocal calls
        matrix = np.atleast_2d(np.asarray(coalitions, dtype=bool))
        if matrix.shape[1] != n_players:
            raise ValueError("external estimator supplied a coalition with wrong width")
        masks = [
            sum((1 << index) for index, included in enumerate(row) if included)
            for row in matrix
        ]
        calls += len(masks)
        if calls > budget:
            raise RuntimeError("external estimator exceeded declared coalition budget")
        observed_masks.update(masks)
        return np.asarray([table.values[mask] for mask in masks], dtype=float)

    approximator_class = getattr(shapiq, _SHAPIQ_CLASSES[method_id])
    approximator = approximator_class(n=n_players, random_state=seed)
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message="Not all budget is required due to the border-trick"
        )
        result = approximator.approximate(budget=budget, game=game)
    values = np.asarray(result.get_n_order_values(1), dtype=float)
    if values.shape != (n_players,) or not np.all(np.isfinite(values)):
        raise RuntimeError("external estimator returned invalid first-order Shapley values")
    return ValuationOutput(
        dict(zip(table.owner_ids, (float(value) for value in values), strict=True)),
        diagnostics={
            "estimand": "ordinary_shapley",
            "logical_calls": calls,
            "unique_coalitions": len(observed_masks),
            "declared_budget": budget,
            "backend": "shapiq",
            "backend_version": shapiq.__version__,
            "estimated": bool(result.estimated),
        },
        utility_calls=calls,
    )


def _official_svarm(
    method_id: str,
    table: CoalitionGameTable,
    *,
    budget: int,
    seed: int,
    repository: str | Path | None,
) -> ValuationOutput:
    if repository is None:
        raise OptionalMethodUnavailable("official_repository_path_missing:svarm")
    root = Path(repository).resolve()
    required = root / "ApproxMethods" / "SVARM"
    if not required.is_dir():
        raise OptionalMethodUnavailable("invalid_official_repository:svarm")
    try:
        commit = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise OptionalMethodUnavailable("unverifiable_official_repository:svarm") from exc
    if commit != _OFFICIAL_SVARM_COMMIT:
        raise OptionalMethodUnavailable(f"unsupported_official_commit:svarm:{commit}")
    if not isinstance(budget, int) or budget < 2 * len(table.owner_ids) + 1:
        raise ValueError("official Stratified SVARM budget is below its fixed initialization cost")

    sys.path.insert(0, str(root))
    try:
        if method_id == "official_stratified_svarm":
            from ApproxMethods.SVARM.StratifiedSVARM import StratifiedSVARM

            estimator = StratifiedSVARM()
        else:
            from ApproxMethods.SVARM.StratifiedSVARMnoReplacement import (
                StratifiedSVARMnoReplacement,
            )

            estimator = StratifiedSVARMnoReplacement()
    finally:
        sys.path.remove(str(root))

    baseline = table.values[0]
    exact_scores = _exact(table).scores

    class TableGame:
        def get_player_number(self):
            return len(table.owner_ids)

        def get_value(self, coalition):
            mask = sum(1 << int(index) for index in coalition)
            return table.values[mask] - baseline

        def get_shapley_values(self):
            return np.asarray([exact_scores[owner] for owner in table.owner_ids])

        def get_name(self):
            return table.content_hash

        def get_game_information(self):
            return {
                "name": self.get_name(),
                "number_of_players": self.get_player_number(),
            }

    numpy_state = np.random.get_state()
    python_state = random.getstate()
    try:
        np.random.seed(seed)
        random.seed(seed)
        estimator.reset(TableGame(), budget, evaluation_penalty=0, step_size=budget)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            estimator.approximate_shapley_values()
        values = np.asarray(estimator.get_estimates(), dtype=float)
    finally:
        np.random.set_state(numpy_state)
        random.setstate(python_state)
    calls = int(estimator.initial_budget - estimator.budget)
    if values.shape != (len(table.owner_ids),) or not np.all(np.isfinite(values)):
        raise RuntimeError("official SVARM implementation returned invalid estimates")
    return ValuationOutput(
        dict(zip(table.owner_ids, (float(value) for value in values), strict=True)),
        diagnostics={
            "estimand": "ordinary_shapley",
            "logical_calls": calls,
            "declared_budget": budget,
            "backend": "official_svarm_repository",
            "source_commit": commit,
            "empty_coalition_normalized": True,
        },
        utility_calls=calls,
    )


def _pydvl_subprocess(
    method_id: str,
    table: CoalitionGameTable,
    *,
    budget: int,
    seed: int,
    python_executable: str | Path | None,
    epsilon: float,
) -> ValuationOutput:
    if python_executable is None:
        raise OptionalMethodUnavailable("pydvl_python_missing")
    # Do not resolve a venv's Python symlink: executing the resolved base
    # interpreter bypasses pyvenv.cfg and therefore its site-packages.
    executable = Path(python_executable).expanduser().absolute()
    if not executable.is_file():
        raise OptionalMethodUnavailable("pydvl_python_missing")
    worker = Path(__file__).resolve().parents[1] / "pydvl_worker.py"
    payload = {
        "method_id": method_id,
        "owner_ids": table.owner_ids,
        "values": [table.values[mask] for mask in range(1 << len(table.owner_ids))],
        "budget": budget,
        "seed": seed,
        "epsilon": epsilon,
    }
    completed = subprocess.run(
        [str(executable), str(worker)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip().splitlines()
        detail = message[-1] if message else "unknown worker failure"
        raise RuntimeError(f"pyDVL worker failed: {detail}")
    report = json.loads(completed.stdout)
    if report["backend_version"] != "0.10.0":
        raise OptionalMethodUnavailable(
            f"unsupported_dependency_version:pydvl=={report['backend_version']}"
        )
    scores = np.asarray(report["scores"], dtype=float)
    calls = int(report["logical_calls"])
    if scores.shape != (len(table.owner_ids),) or not np.all(np.isfinite(scores)):
        raise RuntimeError("pyDVL returned invalid Shapley values")
    if calls > budget:
        raise RuntimeError("pyDVL exceeded declared coalition budget")
    return ValuationOutput(
        dict(zip(table.owner_ids, (float(value) for value in scores), strict=True)),
        diagnostics={
            "estimand": "ordinary_shapley",
            "logical_calls": calls,
            "declared_budget": budget,
            "backend": "pyDVL",
            "backend_version": report["backend_version"],
            "counts": tuple(report["counts"]),
        },
        utility_calls=calls,
    )


def evaluate_sota(
    method_id: str,
    table: CoalitionGameTable,
    *,
    budget: int,
    seed: int,
    **options: Any,
) -> ValuationOutput:
    """Evaluate a frozen SOTA backend on an immutable coalition game."""
    if not isinstance(table, CoalitionGameTable):
        raise TypeError("table must be a CoalitionGameTable")
    minimum = sota_minimum_budget(method_id, len(table.owner_ids))
    if not isinstance(budget, int) or budget < minimum:
        raise ValueError(f"{method_id} requires a budget of at least {minimum}")
    if method_id == "exact_table":
        return _exact(table)
    if method_id in _SHAPIQ_CLASSES:
        return _shapiq(method_id, table, budget=budget, seed=seed)
    if method_id in {"official_stratified_svarm", "official_stratified_svarm_plus"}:
        return _official_svarm(
            method_id,
            table,
            budget=budget,
            seed=seed,
            repository=options.get("official_repo"),
        )
    if method_id == "official_linear_regression_msr":
        repository = options.get("regression_msr_repo")
        if repository is None:
            raise OptionalMethodUnavailable(
                "official_repository_path_missing:regression_msr"
            )
        return run_regression_msr(
            table,
            budget=budget,
            seed=seed,
            official_repo=repository,
            variant="linear",
        )
    if method_id in {"pydvl_vrds", "pydvl_owen", "pydvl_group_testing"}:
        return _pydvl_subprocess(
            method_id,
            table,
            budget=budget,
            seed=seed,
            python_executable=options.get("pydvl_python"),
            epsilon=float(options.get("epsilon", 0.5)),
        )
    raise KeyError(f"unsupported SOTA Shapley method: {method_id}")


__all__ = ["evaluate_sota", "sota_minimum_budget"]
