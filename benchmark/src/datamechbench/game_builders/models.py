"""Predeclared nested model-fidelity ladders."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FidelitySpec:
    name: str
    capacity: int
    cost_ratio: float
    nested_parent: str | None
    mechanism: str


_LADDERS = {
    "tree_ensemble": (
        FidelitySpec("low", 16, 0.20, "medium", "ensemble_width"),
        FidelitySpec("medium", 48, 0.55, "high", "ensemble_width"),
        FidelitySpec("high", 128, 1.00, None, "ensemble_width"),
    ),
    "boosting": (
        FidelitySpec("low", 20, 0.20, "medium", "boosting_round_prefix"),
        FidelitySpec("medium", 60, 0.55, "high", "boosting_round_prefix"),
        FidelitySpec("high", 120, 1.00, None, "boosting_round_prefix"),
    ),
    "neural_head": (
        FidelitySpec("low", 1, 0.25, "medium", "training_epoch_prefix"),
        FidelitySpec("medium", 3, 0.55, "high", "training_epoch_prefix"),
        FidelitySpec("high", 6, 1.00, None, "training_epoch_prefix"),
    ),
}


def fidelity_ladder(model_family: str) -> tuple[FidelitySpec, ...]:
    try:
        return _LADDERS[model_family]
    except KeyError as exc:
        raise ValueError(f"unsupported model family: {model_family}") from exc


__all__ = ["FidelitySpec", "fidelity_ladder"]
