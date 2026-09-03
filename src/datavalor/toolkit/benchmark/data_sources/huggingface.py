"""Optional Hugging Face datasets provider."""

from __future__ import annotations

import random
from typing import Any

from .base import BaseDistribution, DistributionBatch


class HuggingFaceProvider(BaseDistribution):
    name = "dataset.huggingface"

    def __init__(self, dataset: str, split: str = "train", config_name: str | None = None,
                 revision: str | None = None, streaming: bool = False, max_records: int | None = None,
                 data_files: Any = None, load_kwargs: dict[str, Any] | None = None):
        self.dataset, self.split, self.config_name, self.revision = dataset, split, config_name, revision
        self.streaming, self.max_records, self.data_files, self.load_kwargs = streaming, max_records, data_files, load_kwargs or {}

    def generate(self, *, rng: random.Random, context=None) -> DistributionBatch:
        del rng, context
        try:
            from datasets import load_dataset
        except ImportError as exc:
            raise ImportError("This provider requires optional dependency datasets") from exc
        kwargs = dict(self.load_kwargs)
        if self.revision is not None: kwargs["revision"] = self.revision
        if self.data_files is not None: kwargs["data_files"] = self.data_files
        dataset = load_dataset(self.dataset, self.config_name, split=self.split, streaming=self.streaming, **kwargs)
        rows = []
        for index, row in enumerate(dataset):
            if self.max_records is not None and index >= self.max_records: break
            rows.append(dict(row))
        return DistributionBatch(rows, {"source_kind": "real_dataset", "catalog": "huggingface", "dataset": self.dataset, "split": self.split, "revision": self.revision})
