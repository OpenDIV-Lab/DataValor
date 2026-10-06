from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from datamechbench.game_builders import (
    CoalitionTableBuilder,
    DatasetManifest,
    partition_indices,
)
from datamechbench.game_builders.models import fidelity_ladder
from datamechbench.game_builders.run_config import build_smoke_jobs
from datamechbench.settings.valuation_generalization import generalization_settings


@pytest.mark.parametrize("scheme", ["iid", "label_skew", "quantity_skew", "domain"])
def test_owner_partitions_are_deterministic_complete_and_disjoint(scheme: str) -> None:
    labels = np.asarray([index % 4 for index in range(80)])
    domains = np.asarray([index % 8 for index in range(80)])
    first = partition_indices(
        labels,
        n_owners=8,
        scheme=scheme,
        imbalance_ratio=4,
        seed=13,
        domains=domains,
    )
    second = partition_indices(
        labels,
        n_owners=8,
        scheme=scheme,
        imbalance_ratio=4,
        seed=13,
        domains=domains,
    )
    assert first == second
    flattened = [row for rows in first.values() for row in rows]
    assert sorted(flattened) == list(range(80))
    assert len(flattened) == len(set(flattened))
    assert set(first) == {f"o{i}" for i in range(8)}


def test_dataset_manifest_hash_changes_with_any_protocol_field() -> None:
    base = DatasetManifest("digits", "image", "abc123", 8, "iid", 1, 42)
    same = DatasetManifest("digits", "image", "abc123", 8, "iid", 1, 42)
    changed = DatasetManifest("digits", "image", "abc123", 8, "label_skew", 1, 42)
    assert base.content_hash == same.content_hash
    assert base.content_hash != changed.content_hash


def test_partial_coalition_cache_is_rejected_then_resumed(tmp_path: Path) -> None:
    manifest = DatasetManifest("fixture", "tabular", "data", 3, "iid", 1, 0)
    builder = CoalitionTableBuilder(tmp_path)
    calls: list[int] = []

    def interrupted(mask: int) -> float:
        calls.append(mask)
        if mask == 3:
            raise RuntimeError("interrupt")
        return float(mask.bit_count())

    with pytest.raises(RuntimeError, match="interrupt"):
        builder.build(manifest, "high", interrupted)
    assert builder.load_complete(manifest, "high") is None
    assert calls == [0, 1, 2, 3]

    resumed_calls: list[int] = []
    table = builder.build(
        manifest,
        "high",
        lambda mask: resumed_calls.append(mask) or float(mask.bit_count()),
    )
    assert resumed_calls == [3, 4, 5, 6, 7]
    assert len(table.values) == 8
    assert builder.load_complete(manifest, "high").content_hash == table.content_hash


@pytest.mark.parametrize("family", ["tree_ensemble", "boosting", "neural_head"])
def test_every_model_family_has_three_predeclared_nested_fidelities(family: str) -> None:
    ladder = fidelity_ladder(family)
    assert tuple(item.name for item in ladder) == ("low", "medium", "high")
    assert all(item.cost_ratio > 0 for item in ladder)
    assert [item.capacity for item in ladder] == sorted(item.capacity for item in ladder)
    assert ladder[0].nested_parent == "medium"
    assert ladder[1].nested_parent == "high"
    assert ladder[2].nested_parent is None


def test_smoke_config_builds_one_content_addressed_job_per_model_family(
    tmp_path: Path,
) -> None:
    config = Path(__file__).parents[1] / "configs" / "elr_vrds_smoke.yaml"
    jobs = build_smoke_jobs(
        config,
        settings=generalization_settings(),
        output_root=tmp_path,
    )
    assert len(jobs) == 4
    assert len({job.job_id for job in jobs}) == 4
    assert {job.env["DATAMECH_MODALITY"] for job in jobs} == {
        "tabular",
        "image",
        "text",
    }
    assert all("datamechbench.game_builders.smoke" in job.command for job in jobs)
    assert all(job.output_dir.is_relative_to(tmp_path) for job in jobs)
