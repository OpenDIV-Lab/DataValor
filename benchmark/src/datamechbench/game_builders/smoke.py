"""Tiny CUDA-backed end-to-end coalition-game builder used by smoke tests."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from ..settings.valuation_generalization import generalization_settings
from . import CoalitionTableBuilder, DatasetManifest


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True))
    os.replace(temporary, path)


def build_fixture(setting_id: str, seed: int, output_dir: Path) -> dict[str, object]:
    import torch

    settings = {item.setting_id: item for item in generalization_settings()}
    setting = settings[setting_id]
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for the GPU smoke builder")
    if torch.cuda.current_device() != 0:
        raise RuntimeError("a single visible physical GPU must map to local CUDA index 0")

    device = torch.device("cuda:0")
    setting_offset = int.from_bytes(
        hashlib.sha256(setting.setting_id.encode()).digest()[:4], "big"
    )
    fixture_seed = (seed + setting_offset) % (2**31)
    torch.manual_seed(fixture_seed)
    torch.cuda.manual_seed_all(fixture_seed)
    torch.cuda.reset_peak_memory_stats(device)
    generator = torch.Generator(device="cpu").manual_seed(fixture_seed + 971)
    owner_features = torch.randn(
        setting.n_owners, 32, generator=generator, dtype=torch.float32
    ).to(device)
    direction = torch.randn(32, generator=generator, dtype=torch.float32).to(device)
    direction /= direction.norm().clamp_min(1e-7)
    manifest = DatasetManifest(
        dataset_id=f"fixture:{setting.dataset_id}",
        modality=setting.modality,
        dataset_hash=f"cuda-fixture-v2-setting{setting_offset}-seed{seed}",
        n_owners=setting.n_owners,
        partition=setting.partition,
        imbalance_ratio=setting.imbalance_ratio,
        split_seed=seed,
    )
    builder = CoalitionTableBuilder(output_dir / "tables")
    calls: dict[str, int] = {}
    tables: dict[str, str] = {}

    for fidelity in setting.fidelities:
        calls[fidelity.name] = 0
        quality = fidelity.capacity / setting.fidelities[-1].capacity

        def evaluate(mask: int, *, quality: float = quality, name: str = fidelity.name) -> float:
            calls[name] += 1
            membership = torch.tensor(
                [(mask >> index) & 1 for index in range(setting.n_owners)],
                device=device,
                dtype=torch.float32,
            )
            aggregate = membership @ owner_features
            size = membership.sum()
            signal = aggregate @ direction
            interaction = aggregate.square().mean().sqrt()
            # All fidelities share the same limiting utility; smaller nested models
            # have a deterministic approximation residual, creating a realistic
            # control-variate problem without downloading data in the smoke test.
            value = torch.tanh(signal / (size + 1.0))
            value += 0.08 * torch.log1p(size) * interaction / (interaction + 1.0)
            value += (1.0 - quality) * 0.03 * torch.sin(signal)
            return float(value.item())

        table = builder.build(manifest, fidelity.name, evaluate)
        tables[fidelity.name] = table.content_hash

    torch.cuda.synchronize(device)
    summary: dict[str, object] = {
        "setting_id": setting.setting_id,
        "modality": setting.modality,
        "model_family": setting.model_family,
        "seed": seed,
        "physical_gpu": int(os.environ["DATAMECH_PHYSICAL_GPU"]),
        "local_cuda_index": torch.cuda.current_device(),
        "peak_gpu_bytes": int(torch.cuda.max_memory_allocated(device)),
        "new_coalitions": calls,
        "table_hashes": tables,
        "manifest_hash": manifest.content_hash,
    }
    _atomic_json(output_dir / "summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--setting-id", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    print(json.dumps(build_fixture(args.setting_id, args.seed, args.output_dir), sort_keys=True))


if __name__ == "__main__":
    main()
