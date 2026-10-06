"""Paper-faithful adapters for the NeurIPS 2025 Regression MSR estimators."""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import numpy as np

from ..coalition_games import CoalitionGameTable
from ..models import ValuationOutput
from .valuation_shapley import OptionalMethodUnavailable

_OFFICIAL_REGRESSION_MSR_COMMIT = "77525daf334aadffa8157b6d2693dc34ce33ecf6"


class _CountingTableModel:
    def __init__(self, table: CoalitionGameTable) -> None:
        self.table = table
        self.calls = 0

    def predict(self, coalitions) -> np.ndarray:
        matrix = np.atleast_2d(np.asarray(coalitions, dtype=float))
        if matrix.shape[1] != len(self.table.owner_ids):
            raise ValueError("Regression MSR emitted a coalition with the wrong width")
        masks = [
            sum(1 << index for index, included in enumerate(row) if included >= 0.5)
            for row in matrix
        ]
        self.calls += len(masks)
        return np.asarray([self.table.values[mask] for mask in masks], dtype=float)


def run_regression_msr(
    table: CoalitionGameTable,
    *,
    budget: int,
    seed: int,
    official_repo: str | Path,
    variant: str,
) -> ValuationOutput:
    """Estimate Shapley values with the authors' LinearMSR or TreeMSR code."""

    if variant not in {"linear", "tree", "linear_all", "tree_all"}:
        raise ValueError("variant must be linear, tree, linear_all, or tree_all")
    if not isinstance(budget, int) or budget < 1:
        raise ValueError("budget must be a positive integer")
    root = Path(official_repo).resolve()
    if not (root / "regressionMSR/estimators/regMSR.py").is_file():
        raise OptionalMethodUnavailable("invalid_official_repository:regression_msr")
    commit = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if commit != _OFFICIAL_REGRESSION_MSR_COMMIT:
        raise OptionalMethodUnavailable(
            f"unsupported_official_commit:regression_msr:{commit}"
        )

    sys.path.insert(0, str(root))
    try:
        module = importlib.import_module("regressionMSR.estimators.regMSR")
        all_module = importlib.import_module("regressionMSR.estimators.regMSR_all")
    finally:
        sys.path.remove(str(root))
    estimator_type = {
        "linear": module.LinearMSR,
        "tree": module.TreeMSR,
        "linear_all": all_module.LinearMSRAll,
        "tree_all": all_module.TreeMSRAll,
    }[variant]
    model = _CountingTableModel(table)
    owner_count = len(table.owner_ids)
    endpoint_calls = 2 if variant.startswith("linear") else 0
    sample_budget = budget - endpoint_calls
    minimum_samples = 20
    if sample_budget < minimum_samples and sample_budget < len(table.values):
        raise ValueError(
            f"Regression MSR budget must leave at least {minimum_samples} samples"
        )
    estimator = estimator_type(
        model,
        np.zeros((1, owner_count), dtype=float),
        "shapley",
        seed=seed,
    )
    folds = 1 if variant.endswith("_all") else 10
    explain_kwargs = {"num_samples": sample_budget}
    if folds == 10:
        explain_kwargs["k"] = folds
    values = np.asarray(
        estimator.explain(
            np.ones((1, owner_count), dtype=float),
            **explain_kwargs,
        ),
        dtype=float,
    ).reshape(-1)
    if values.shape != (owner_count,) or not np.all(np.isfinite(values)):
        raise RuntimeError("Regression MSR returned invalid Shapley values")
    if model.calls > budget:
        raise RuntimeError(
            f"Regression MSR exceeded its budget: {model.calls} > {budget}"
        )
    return ValuationOutput(
        dict(zip(table.owner_ids, map(float, values), strict=True)),
        diagnostics={
            "backend": f"official_{variant}_regression_msr",
            "source_commit": _OFFICIAL_REGRESSION_MSR_COMMIT,
            "variant": variant,
            "declared_budget": budget,
            "logical_calls": model.calls,
            "endpoint_calls": endpoint_calls,
            "sample_budget": sample_budget,
            "folds": folds,
        },
        utility_calls=model.calls,
    )


__all__ = ["run_regression_msr"]
