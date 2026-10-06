"""Python 3.10 subprocess worker for frozen pyDVL 0.10 coalition games."""

from __future__ import annotations

import json
import sys
import warnings

import numpy as np
from joblib import parallel_config
from pydvl import __version__ as pydvl_version
from pydvl.valuation import (
    Dataset,
    GridOwenStrategy,
    GroupTestingShapleyValuation,
    NoStopping,
    OwenSampler,
    ShapleyValuation,
    VRDSSampler,
)
from pydvl.valuation.utility.base import UtilityBase

warnings.filterwarnings("ignore")


def evaluate_payload(payload) -> dict:
    method_id = payload["method_id"]
    owners = tuple(payload["owner_ids"])
    values = np.asarray(payload["values"], dtype=float)
    budget = int(payload["budget"])
    seed = int(payload["seed"])
    n_players = len(owners)
    calls = [0]

    class TableUtility(UtilityBase):
        def __call__(self, sample) -> float:
            calls[0] += 1
            subset = () if sample is None else sample.subset
            mask = sum(1 << int(index) for index in subset)
            return float(values[mask])

    data = Dataset(
        np.arange(n_players, dtype=float)[:, None],
        np.zeros(n_players),
        data_names=owners,
    )
    utility = TableUtility()
    if method_id == "pydvl_vrds":
        samples_per_index = budget // (2 * n_players)
        if samples_per_index < n_players:
            raise ValueError(
                "pydvl_vrds budget must cover every player/coalition-size stratum"
            )
        sampler = VRDSSampler(n_samples_per_index=samples_per_index, seed=seed)
        valuation = ShapleyValuation(
            utility, sampler, NoStopping(sampler), progress=False, show_warnings=False
        )
    elif method_id == "pydvl_owen":
        outer_samples = budget // (4 * n_players)
        if outer_samples < 1:
            raise ValueError("pydvl_owen budget is below one outer integration sample")
        sampler = OwenSampler(
            GridOwenStrategy(n_samples_outer=outer_samples),
            n_samples_inner=2,
            seed=seed,
        )
        valuation = ShapleyValuation(
            utility, sampler, NoStopping(sampler), progress=False, show_warnings=False
        )
    elif method_id == "pydvl_group_testing":
        if budget < 3:
            raise ValueError("pydvl_group_testing budget must be at least three")
        valuation = GroupTestingShapleyValuation(
            utility,
            n_samples=budget - 1,
            epsilon=float(payload.get("epsilon", 0.5)),
            progress=False,
            seed=seed,
        )
    else:
        raise KeyError(f"unknown pyDVL worker method: {method_id}")

    with parallel_config(n_jobs=1, backend="threading"):
        valuation.fit(data)
    result = valuation.result
    if calls[0] > budget:
        raise RuntimeError(f"pyDVL exceeded budget: {calls[0]} > {budget}")
    return {
        "scores": [float(value) for value in result.values],
        "logical_calls": calls[0],
        "counts": [int(value) for value in result.counts],
        "backend_version": pydvl_version,
    }


def main() -> None:
    payload = json.load(sys.stdin)
    if isinstance(payload, list):
        json.dump([evaluate_payload(item) for item in payload], sys.stdout)
    else:
        json.dump(evaluate_payload(payload), sys.stdout)


if __name__ == "__main__":
    main()
