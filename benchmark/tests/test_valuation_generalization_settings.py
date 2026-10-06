from __future__ import annotations

from pathlib import Path

import yaml
from datamechbench.settings.valuation_generalization import generalization_settings


def test_generalization_registry_covers_modalities_families_and_eight_exact_games() -> None:
    settings = generalization_settings()
    exact = [item for item in settings if item.reference_kind == "exact"]
    scale = [item for item in settings if item.reference_kind == "consensus"]

    assert len(exact) >= 8
    assert {item.modality for item in exact} == {"tabular", "image", "text"}
    assert {item.model_family for item in exact} >= {
        "tree_ensemble",
        "boosting",
        "neural_head",
    }
    assert {item.n_owners for item in exact} >= {6, 8, 10}
    assert {item.n_owners for item in scale} >= {12, 16, 20}
    assert all(item.n_owners <= 10 for item in exact)
    assert all(item.n_owners >= 12 for item in scale)
    assert all(len(item.fidelities) >= 3 for item in settings)
    assert all(item.split in {"development", "confirmatory"} for item in settings)


def test_elr_configs_never_schedule_gpu_zero_and_keep_holdout_separate() -> None:
    root = Path(__file__).resolve().parents[1] / "configs"
    configs = {
        name: yaml.safe_load((root / f"elr_vrds_{name}.yaml").read_text())
        for name in ("smoke", "development", "confirmatory")
    }
    assert configs["smoke"]["physical_gpus"] == [1]
    assert configs["development"]["physical_gpus"] == [1, 2, 3, 4, 5, 6, 7]
    assert configs["confirmatory"]["physical_gpus"] == [1, 2, 3, 4, 5, 6, 7]
    assert all(0 not in config["physical_gpus"] for config in configs.values())
    assert configs["development"]["split"] == "development"
    assert configs["confirmatory"]["split"] == "confirmatory"
    assert set(configs["development"]["setting_ids"]).isdisjoint(
        configs["confirmatory"]["setting_ids"]
    )
