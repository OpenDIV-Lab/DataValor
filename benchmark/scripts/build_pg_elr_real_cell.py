#!/usr/bin/env python3
"""Build one resumable real PG-ELR development coalition game."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import numpy as np
from datamechbench.game_builders.real_coalitions import build_real_coalition_tables
from datamechbench.game_builders.real_data import (
    audit_split_isolation,
    load_real_dataset,
    split_and_partition,
)
from datamechbench.game_builders.real_features import (
    PublicFeatureConfig,
    extract_public_features,
)
from datamechbench.game_builders.real_models import ModelTrajectoryConfig
from datamechbench.game_builders.real_sources import SourcePolicy
from datamechbench.pg_elr_development import real_build_spec

_SEEDS = {"iid": 11, "label_skew": 29, "quantity_skew": 47}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset",
        choices=("breast_cancer", "wine", "adult", "ag_news", "20newsgroups"),
        required=True,
    )
    parser.add_argument("--partition", choices=tuple(_SEEDS), required=True)
    parser.add_argument("--source-cache", type=Path, default=Path("outputs/elr_vrds_real_sources/cache"))
    parser.add_argument("--feature-cache", type=Path, default=Path("outputs/elr_vrds_real_features"))
    parser.add_argument("--output-root", type=Path, default=Path("outputs/elr_vrds_real_core"))
    args = parser.parse_args()

    spec = real_build_spec(args.dataset)
    seed = _SEEDS[args.partition]
    token = {
        "breast_cancer": "breast-rf",
        "wine": "wine-rf",
        "adult": "adult-gb",
        "ag_news": "agnews-head",
        "20newsgroups": "20news-head",
    }[args.dataset]
    setting_id = f"real-{token}-n8-{args.partition}-s{seed}"
    started = time.perf_counter()
    bundle = load_real_dataset(
        args.dataset,
        cache_dir=args.source_cache,
        cap=spec.cap,
        source_policy=SourcePolicy(allow_download=False),
    )
    feature_device = "cpu"
    model_device = "cuda:0" if spec.model_family == "neural_head" else "cpu"
    features = extract_public_features(
        bundle,
        PublicFeatureConfig(
            kind=spec.feature_kind,
            transform_id=spec.transform_id,
            schema_id=spec.schema_id,
        ),
        cache_dir=args.feature_cache,
        device=feature_device,
    )
    manifest = split_and_partition(
        bundle,
        setting_id=setting_id,
        n_owners=8,
        split_seed=seed,
        partition=args.partition,
        imbalance_ratio=4,
    )
    isolation_errors = audit_split_isolation(manifest)
    if isolation_errors:
        raise RuntimeError(f"split isolation failed: {isolation_errors}")
    tables = build_real_coalition_tables(
        manifest,
        features,
        ModelTrajectoryConfig(
            model_family=spec.model_family,
            task=bundle.task,
            global_classes=tuple(np.unique(bundle.targets).tolist()),
        ),
        cache_dir=args.output_root / "games",
        device=model_device,
    )
    high = np.asarray([tables.tables["high"].values[mask] for mask in range(256)])
    medium = np.asarray([tables.tables["medium"].values[mask] for mask in range(256)])
    high_marginals = []
    residual_marginals = []
    for player in range(8):
        bit = 1 << player
        for mask in range(256):
            if mask & bit:
                continue
            high_delta = high[mask | bit] - high[mask]
            medium_delta = medium[mask | bit] - medium[mask]
            high_marginals.append(high_delta)
            residual_marginals.append(high_delta - medium_delta)
    denominator = float(np.var(high_marginals))
    residual_efficiency = float(np.var(residual_marginals) / denominator) if denominator else 0.0
    summary = {
        "setting_id": setting_id,
        "dataset_id": args.dataset,
        "partition": args.partition,
        "split_seed": seed,
        "input_hash": tables.input_hash,
        "content_hash": tables.content_hash,
        "dataset_hash": bundle.dataset_hash,
        "feature_hash": features.feature_hash,
        "correlation_medium_high": float(np.corrcoef(medium, high)[0, 1]),
        "residual_efficiency_medium": residual_efficiency,
        "trajectory_builds": tables.trajectory_builds,
        "elapsed_seconds": time.perf_counter() - started,
        "device": model_device,
        "physical_gpu": int(os.environ["CUDA_VISIBLE_DEVICES"].split(",")[0])
        if model_device.startswith("cuda")
        else None,
    }
    args.output_root.mkdir(parents=True, exist_ok=True)
    summary_path = args.output_root / f"{args.dataset}_{args.partition}_s{seed}_summary.json"
    temporary = summary_path.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, summary_path)
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
