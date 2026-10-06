"""Turn a frozen game-building YAML file into resumable GPU jobs."""

from __future__ import annotations

import hashlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from ..gpu_scheduler import GpuJob
from ..settings.valuation_generalization import GeneralizationSetting


@dataclass(frozen=True)
class RealGameCell:
    setting_id: str
    dataset_id: str
    evidence_split: str
    partition: str
    split_seed: int
    n_owners: int
    model_family: str
    feature_kind: str
    status: str = "declared"
    reason: str | None = None


_PARTITION_SEEDS = {"iid": 11, "label_skew": 29, "quantity_skew": 47}


def expand_real_game_matrix(
    settings: Iterable[Any],
    *,
    unavailable_partitions: Mapping[tuple[str, str], str] | None = None,
) -> tuple[RealGameCell, ...]:
    """Expand frozen settings while retaining impossible cells as reasoned N/A."""

    unavailable = dict(unavailable_partitions or {})
    feature_kinds = {
        "adult": "mixed_tabular_hashing",
        "ag_news": "text_hashing",
        "20newsgroups": "text_hashing",
        "digits": "digits_raw",
        "fashion_mnist": "resnet18_frozen",
        "cifar10_subset": "resnet18_frozen",
    }
    cells: list[RealGameCell] = []
    for setting in settings:
        for partition in setting.partitions:
            if partition not in _PARTITION_SEEDS:
                raise ValueError(f"unsupported real partition: {partition}")
            split_seed = _PARTITION_SEEDS[partition]
            if split_seed not in setting.split_seeds:
                raise ValueError(
                    f"setting {setting.setting_id} does not allow split seed {split_seed}"
                )
            reason = unavailable.get((setting.dataset_id, partition))
            if reason is not None and not str(reason).strip():
                raise ValueError("structured N/A reasons must be non-empty")
            cells.append(
                RealGameCell(
                    setting.setting_id,
                    setting.dataset_id,
                    setting.evidence_split,
                    partition,
                    split_seed,
                    setting.n_owners,
                    setting.model_family,
                    feature_kinds.get(setting.dataset_id, "tabular_numeric"),
                    "not_applicable" if reason is not None else "declared",
                    str(reason) if reason is not None else None,
                )
            )
    return tuple(cells)


def build_smoke_jobs(
    config_path: Path,
    *,
    settings: Iterable[GeneralizationSetting],
    output_root: Path | None = None,
) -> tuple[GpuJob, ...]:
    config_path = Path(config_path).resolve()
    payload = yaml.safe_load(config_path.read_text())
    if not payload.get("fixture_mode"):
        raise ValueError("build_smoke_jobs only accepts fixture_mode configurations")
    setting_by_id = {item.setting_id: item for item in settings}
    selected = [setting_by_id[item] for item in payload["setting_ids"]]
    families = {item.model_family for item in selected}
    required_families = {"tree_ensemble", "boosting", "neural_head"}
    if not required_families.issubset(families):
        missing = sorted(required_families - families)
        raise ValueError(f"smoke config is missing model families: {missing}")

    repository = config_path.parents[2]
    root = (
        Path(output_root)
        if output_root is not None
        else repository / Path(payload["cache_dir"])
    )
    python_path = os.pathsep.join(
        filter(
            None,
            (
                str(repository / "benchmark" / "src"),
                str(repository / "src"),
                os.environ.get("PYTHONPATH", ""),
            ),
        )
    )
    builder_hash = hashlib.sha256(
        config_path.read_bytes() + Path(__file__).with_name("smoke.py").read_bytes()
    ).hexdigest()
    jobs: list[GpuJob] = []
    for setting in selected:
        for seed in payload["seeds"]:
            job_id = f"{setting.setting_id}-seed{seed}"
            job_output = root / job_id
            jobs.append(
                GpuJob(
                    job_id=job_id,
                    command=(
                        sys.executable,
                        "-m",
                        "datamechbench.game_builders.smoke",
                        "--setting-id",
                        setting.setting_id,
                        "--seed",
                        str(seed),
                        "--output-dir",
                        str(job_output),
                    ),
                    output_dir=job_output,
                    env={
                        "PYTHONPATH": python_path,
                        "DATAMECH_MODALITY": setting.modality,
                        "DATAMECH_MODEL_FAMILY": setting.model_family,
                        "DATAMECH_BUILDER_HASH": builder_hash,
                    },
                )
            )
    return tuple(jobs)


__all__ = ["RealGameCell", "build_smoke_jobs", "expand_real_game_matrix"]
