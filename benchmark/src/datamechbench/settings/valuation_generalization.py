"""Predeclared ELR-VRDS generalization and scale-stress settings."""

from __future__ import annotations

from dataclasses import dataclass

from ..game_builders.models import FidelitySpec, fidelity_ladder


@dataclass(frozen=True)
class GeneralizationSetting:
    setting_id: str
    modality: str
    dataset_id: str
    model_family: str
    n_owners: int
    partition: str
    imbalance_ratio: int
    reference_kind: str
    split: str
    fidelities: tuple[FidelitySpec, ...]


def _setting(
    setting_id: str,
    modality: str,
    dataset_id: str,
    model_family: str,
    n_owners: int,
    *,
    partition: str = "iid",
    imbalance_ratio: int = 1,
    reference_kind: str = "exact",
    split: str = "development",
) -> GeneralizationSetting:
    return GeneralizationSetting(
        setting_id,
        modality,
        dataset_id,
        model_family,
        n_owners,
        partition,
        imbalance_ratio,
        reference_kind,
        split,
        fidelity_ladder(model_family),
    )


def generalization_settings() -> tuple[GeneralizationSetting, ...]:
    return (
        _setting("gen-breast-rf-n8", "tabular", "breast_cancer", "tree_ensemble", 8),
        _setting("gen-wine-rf-n6", "tabular", "wine", "tree_ensemble", 6, partition="label_skew"),
        _setting("gen-adult-gb-n8", "tabular", "adult", "boosting", 8, imbalance_ratio=4),
        _setting("gen-california-gb-n10", "tabular", "california_housing", "boosting", 10),
        _setting("gen-digits-head-n8", "image", "digits", "neural_head", 8),
        _setting("gen-fashion-head-n8", "image", "fashion_mnist", "neural_head", 8, split="confirmatory"),
        _setting("gen-cifar-head-n10", "image", "cifar10_subset", "neural_head", 10, partition="domain", split="confirmatory"),
        _setting("gen-agnews-head-n8", "text", "ag_news", "neural_head", 8),
        _setting("gen-20news-head-n6", "text", "20newsgroups", "neural_head", 6, partition="label_skew"),
        _setting("scale-breast-n12", "tabular", "breast_cancer", "tree_ensemble", 12, reference_kind="consensus"),
        _setting("scale-digits-n16", "image", "digits", "neural_head", 16, reference_kind="consensus"),
        _setting("scale-agnews-n20", "text", "ag_news", "neural_head", 20, reference_kind="consensus"),
    )


__all__ = ["GeneralizationSetting", "generalization_settings"]
