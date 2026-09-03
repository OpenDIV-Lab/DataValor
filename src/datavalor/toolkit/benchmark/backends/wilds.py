"""WILDS dataset/split adapter for reproducible benchmark inputs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable

from datavalor.core import ArtifactEnvelope, ComponentSpec, RunContext, require_capability

from ..interfaces import BenchmarkDataProvider
from ..models import BenchmarkCase


def _portable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _portable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_portable(item) for item in value]
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        return _portable(tolist())
    return repr(value)


def _materialize(dataset: Any, limit: int | None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, item in enumerate(dataset):
        if limit is not None and index >= limit:
            break
        if isinstance(item, Mapping):
            record = _portable(item)
        elif isinstance(item, (tuple, list)):
            record = {"input": _portable(item[0])}
            if len(item) > 1:
                record["target"] = _portable(item[1])
            if len(item) > 2:
                record["metadata"] = _portable(item[2])
        else:
            record = {"input": _portable(item)}
        record["sample_index"] = index
        records.append(record)
    return records


class WILDSDataProvider(BenchmarkDataProvider):
    """Load a WILDS dataset and expose it as a DataValor artifact.

    ``loader`` is useful for offline tests and for deployments that maintain a
    local WILDS cache.  The default loader calls the documented
    ``wilds.get_dataset`` function and never downloads unless explicitly
    requested in case parameters.
    """

    def __init__(self, dataset: str | None = None, *, root_dir: str | None = None,
                 loader: Callable[..., Any] | None = None) -> None:
        self.dataset, self.root_dir, self.loader = dataset, root_dir, loader

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("wilds.dataset", "0.1.0", "toolkit.benchmark", "benchmark_data_provider",
                             capabilities=("dataset_loader", "official_split"), requires=("wilds>=2.0",))

    def load(self, case: BenchmarkCase, context: RunContext) -> Mapping[str, ArtifactEnvelope[Any]]:
        parameters = dict(case.parameters)
        dataset_name = self.dataset or parameters.get("dataset")
        if not dataset_name:
            raise ValueError("WILDSDataProvider requires dataset or case.parameters['dataset']")
        loader = self.loader
        if loader is None:
            wilds = require_capability("wilds", "wilds", distribution="wilds", extra="benchmark")
            loader = getattr(wilds, "get_dataset", None)
            if not callable(loader):
                raise RuntimeError("installed WILDS package has no get_dataset function")
        dataset = loader(dataset=dataset_name, root_dir=self.root_dir or parameters.get("root_dir"),
                         download=bool(parameters.get("download", False)))
        split = parameters.get("split")
        subset: Any = dataset
        if split is not None and hasattr(dataset, "get_subset"):
            subset = dataset.get_subset(split)
        if isinstance(subset, (Mapping, list, tuple)):
            payload = _portable(subset)
        elif bool(parameters.get("materialize", True)):
            limit = parameters.get("max_records", 1000)
            payload = _materialize(subset, int(limit) if limit is not None else None)
        else:
            payload = {"dataset": dataset_name, "split": split, "materialized": False}
        artifact_id = f"wilds:{dataset_name}:{split or 'all'}:{case.case_id}"
        artifact = ArtifactEnvelope(
            artifact_id=artifact_id,
            kind="benchmark.wilds_dataset",
            schema_version="datavalor.benchmark.input/v1",
            producer=self.spec,
            payload=payload,
            diagnostics={"dataset": dataset_name, "split": split, "run_id": context.run_id,
                         "official_split": split is not None,
                         "materialized": bool(parameters.get("materialize", True)),
                         "max_records": parameters.get("max_records", 1000)},
        )
        return {str(parameters.get("input_name", "dataset")): artifact}


WildsDataProvider = WILDSDataProvider

__all__ = ["WILDSDataProvider", "WildsDataProvider"]
