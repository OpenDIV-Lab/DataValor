#!/usr/bin/env python3
"""Build one frozen PG-ELR confirmatory game on an allowed physical GPU."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import time
from pathlib import Path

import numpy as np
from datamechbench.game_builders.real_coalitions import build_real_coalition_tables
from datamechbench.game_builders.real_data import (
    audit_split_isolation,
    load_real_dataset,
    split_and_partition,
)
from datamechbench.game_builders.real_features import PublicFeatureConfig, extract_public_features
from datamechbench.game_builders.real_models import ModelTrajectoryConfig
from datamechbench.game_builders.real_sources import SourcePolicy
from datamechbench.pg_elr_development import real_build_spec
from datamechbench.real_experiment import authorize_pg_elr_confirmatory

BENCHMARK = Path(__file__).parents[1]
DATASETS = {
    "fashion_mnist": {"owners": 8, "partition": "label_skew", "seed": 29, "token": "fashion"},
    "cifar10_subset": {"owners": 10, "partition": "iid", "seed": 11, "token": "cifar"},
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _current_source_hashes() -> dict[str, str]:
    return {
        "selection_record": _sha256(BENCHMARK / "evidence/pg_elr/selection_record.json"),
        "method_source": _sha256(BENCHMARK / "src/datamechbench/methods/valuation_multifidelity.py"),
        "development_config": _sha256(BENCHMARK / "configs/pg_elr_paper_development.yaml"),
        "confirmatory_config": _sha256(BENCHMARK / "configs/pg_elr_paper_confirmatory.yaml"),
        "statistics_source": _sha256(BENCHMARK / "src/datamechbench/elr_statistics.py"),
        "report_template": _sha256(BENCHMARK / "docs/pg_elr_confirmatory_report_template.md"),
    }


def _measure_prefix_ratio(features, manifest, model_config, *, device: str) -> dict[str, object]:
    import torch

    class_index = {label: index for index, label in enumerate(model_config.global_classes)}

    def fit_epochs(train_features, train_targets, *, seed: int, epochs: int) -> float:
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
        model = torch.nn.Linear(
            int(train_features.shape[1]), len(model_config.global_classes)
        ).to(device)
        optimizer = torch.optim.SGD(model.parameters(), lr=0.05)
        x = torch.as_tensor(train_features, dtype=torch.float32, device=device)
        y = torch.as_tensor(
            np.asarray([class_index[label] for label in train_targets.tolist()]),
            dtype=torch.long,
            device=device,
        )
        loss_function = torch.nn.CrossEntropyLoss()
        torch.cuda.synchronize()
        started = time.perf_counter()
        for _ in range(epochs):
            optimizer.zero_grad(set_to_none=True)
            loss = loss_function(model(x), y)
            loss.backward()
            optimizer.step()
        torch.cuda.synchronize()
        return time.perf_counter() - started

    row_index = {row_id: index for index, row_id in enumerate(features.row_ids)}
    masks = (1, (1 << (manifest.n_owners // 2)) - 1, (1 << manifest.n_owners) - 1)
    details = []
    for mask in masks:
        selected = [
            row_id
            for owner in range(manifest.n_owners)
            if mask & (1 << owner)
            for row_id in manifest.owner_row_ids[f"o{owner}"]
        ]
        indices = np.asarray([row_index[row_id] for row_id in selected], dtype=np.int64)
        train = (features.values[indices], features.targets[indices])
        durations = []
        for repeat in range(5):
            seed = 7000 + mask + repeat
            medium_seconds = fit_epochs(
                train[0], train[1], seed=seed, epochs=3
            )
            high_seconds = fit_epochs(
                train[0], train[1], seed=seed, epochs=6
            )
            durations.append((medium_seconds, high_seconds))
        medium = statistics.median(pair[0] for pair in durations)
        high = statistics.median(pair[1] for pair in durations)
        details.append({"mask": mask, "medium_seconds": medium, "high_seconds": high, "ratio": medium / high})
    ratios = np.asarray([item["ratio"] for item in details], dtype=float)
    return {
        "details": details,
        "ratio_q1": float(np.quantile(ratios, 0.25)),
        "ratio_median": float(np.quantile(ratios, 0.5)),
        "ratio_q3": float(np.quantile(ratios, 0.75)),
        "repetitions": 5,
        "measurement": "wall_clock_replay_of_frozen_3_epoch_and_6_epoch_prefixes",
    }


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", choices=tuple(DATASETS), required=True)
    parser.add_argument("--source-cache", type=Path, default=Path("outputs/elr_vrds_real_sources/cache"))
    parser.add_argument("--feature-cache", type=Path, default=Path("outputs/pg_elr_paper/confirmatory/features"))
    parser.add_argument("--output-root", type=Path, default=Path("outputs/pg_elr_paper/confirmatory/games"))
    args = parser.parse_args()

    visible = tuple(int(value) for value in os.environ.get("CUDA_VISIBLE_DEVICES", "").split(",") if value)
    if len(visible) != 1 or visible[0] not in range(1, 8):
        raise RuntimeError("exactly one physical GPU in 1..7 must be visible")
    marker = BENCHMARK / "evidence/pg_elr/confirmatory_protocol_freeze.json"
    authorization = authorize_pg_elr_confirmatory(
        marker, expected_source_hashes=_current_source_hashes()
    )

    declared = DATASETS[args.dataset]
    spec = real_build_spec(args.dataset)
    setting_id = (
        f"real-{declared['token']}-head-n{declared['owners']}-"
        f"{declared['partition']}-s{declared['seed']}"
    )
    started = time.perf_counter()
    bundle = load_real_dataset(
        args.dataset,
        cache_dir=args.source_cache,
        cap=spec.cap,
        source_policy=SourcePolicy(allow_download=False),
    )
    features = extract_public_features(
        bundle,
        PublicFeatureConfig(kind=spec.feature_kind, transform_id=spec.transform_id),
        cache_dir=args.feature_cache,
        device="cuda:0",
    )
    manifest = split_and_partition(
        bundle,
        setting_id=setting_id,
        n_owners=int(declared["owners"]),
        split_seed=int(declared["seed"]),
        partition=str(declared["partition"]),
        imbalance_ratio=4,
    )
    isolation_errors = audit_split_isolation(manifest)
    if isolation_errors:
        raise RuntimeError(f"split isolation failed: {isolation_errors}")
    model_config = ModelTrajectoryConfig(
        model_family=spec.model_family,
        task=bundle.task,
        global_classes=tuple(np.unique(bundle.targets).tolist()),
    )
    tables = build_real_coalition_tables(
        manifest, features, model_config, cache_dir=args.output_root / "cache", device="cuda:0"
    )
    replay = build_real_coalition_tables(
        manifest, features, model_config, cache_dir=args.output_root / "cache", device="cuda:0"
    )
    if replay.content_hash != tables.content_hash or replay.trajectory_builds != 0:
        raise RuntimeError("deterministic coalition replay failed")
    costs = _measure_prefix_ratio(features, manifest, model_config, device="cuda:0")
    costs["physical_gpu"] = visible[0]
    costs["protocol_hash"] = authorization.protocol_hash

    summary = {
        "setting_id": setting_id,
        "dataset_id": args.dataset,
        "partition": declared["partition"],
        "split_seed": declared["seed"],
        "owner_count": declared["owners"],
        "owner_row_counts": {
            f"owner-{index}": len(manifest.owner_row_ids[f"o{index}"])
            for index in range(int(declared["owners"]))
        },
        "input_hash": tables.input_hash,
        "content_hash": tables.content_hash,
        "dataset_hash": bundle.dataset_hash,
        "feature_hash": features.feature_hash,
        "feature_cache_key": features.cache_key,
        "feature_cache_hit": features.cache_hit,
        "feature_extraction_seconds": features.extraction_seconds,
        "feature_peak_gpu_bytes": features.peak_gpu_bytes,
        "feature_package_versions": dict(features.package_versions),
        "weight_hash": features.weight_hash,
        "coalitions": 1 << int(declared["owners"]),
        "trajectory_builds": tables.trajectory_builds,
        "replay_verified": True,
        "split_isolation_verified": True,
        "elapsed_seconds": time.perf_counter() - started,
        "device": "cuda:0",
        "physical_gpu": visible[0],
        "protocol_hash": authorization.protocol_hash,
    }
    _atomic_json(args.output_root / f"{args.dataset}_summary.json", summary)
    _atomic_json(args.output_root / f"{args.dataset}_costs.json", costs)
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
