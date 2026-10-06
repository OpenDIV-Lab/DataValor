"""Frozen registry for real-data ELR-VRDS experiments."""

from __future__ import annotations

from dataclasses import dataclass

from ..game_builders.models import FidelitySpec, fidelity_ladder
from ..game_builders.real_sources import declared_real_sources

REAL_SPLIT_SEEDS = (11, 29, 47)
REAL_GPU_IDS = (1, 2, 3, 4, 5, 6, 7)


@dataclass(frozen=True)
class RealValuationSetting:
    setting_id: str
    dataset_id: str
    modality: str
    task: str
    model_family: str
    n_owners: int
    evidence_split: str
    cap: int | None
    partitions: tuple[str, ...]
    imbalance_ratio: int
    split_seeds: tuple[int, ...]
    budgets: tuple[int, int]
    fidelities: tuple[FidelitySpec, ...]
    allowed_replacements: tuple[str, ...]
    gpu_ids: tuple[int, ...]


def _setting(
    setting_id: str,
    dataset_id: str,
    model_family: str,
    n_owners: int = 8,
    *,
    evidence_split: str = "development",
) -> RealValuationSetting:
    source = declared_real_sources()[dataset_id]
    capped = {"adult", "california_housing", "ag_news", "20newsgroups", "fashion_mnist", "cifar10_subset"}
    partitions = (
        ("label_skew",)
        if dataset_id == "fashion_mnist"
        else ("iid",)
        if dataset_id == "cifar10_subset"
        else ("iid", "label_skew", "quantity_skew")
    )
    return RealValuationSetting(
        setting_id=setting_id,
        dataset_id=dataset_id,
        modality=source.modality,
        task=source.task,
        model_family=model_family,
        n_owners=n_owners,
        evidence_split=evidence_split,
        cap=6000 if dataset_id in capped else None,
        partitions=partitions,
        imbalance_ratio=4,
        split_seeds=REAL_SPLIT_SEEDS,
        budgets=(192, 224) if n_owners == 8 else (448, 640),
        fidelities=fidelity_ladder(model_family),
        allowed_replacements=source.allowed_replacements,
        gpu_ids=REAL_GPU_IDS,
    )


def real_valuation_settings() -> tuple[RealValuationSetting, ...]:
    return (
        _setting("real-breast-rf-n8", "breast_cancer", "tree_ensemble"),
        _setting("real-wine-rf-n8", "wine", "tree_ensemble"),
        _setting("real-adult-gb-n8", "adult", "boosting"),
        _setting("real-california-gb-n8", "california_housing", "boosting"),
        _setting("real-diabetes-gb-n8", "diabetes", "boosting"),
        _setting("real-digits-head-n8", "digits", "neural_head"),
        _setting("real-agnews-head-n8", "ag_news", "neural_head"),
        _setting("real-20news-head-n8", "20newsgroups", "neural_head"),
        _setting(
            "real-fashion-head-n8", "fashion_mnist", "neural_head",
            evidence_split="confirmatory",
        ),
        _setting(
            "real-cifar-head-n10", "cifar10_subset", "neural_head", 10,
            evidence_split="confirmatory",
        ),
    )


__all__ = [
    "REAL_GPU_IDS",
    "REAL_SPLIT_SEEDS",
    "RealValuationSetting",
    "real_valuation_settings",
]
